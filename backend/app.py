"""Backend for the 'mailer' module — служба рассылок.

Auth: nginx adds X-Employee-Id header after auth_request /_auth/verify.
      corper-shared.ProxyEmployee builds a user object from that header.

DB:   DATABASE_URL is injected by deploy-agent from core.module_secret.

Multi-company / permissions:
    Don't trust `current_user.company_id` for filtering — it's the user's
    *default* company, not the one selected in the shell. Use
    `corper_shared.context.active_company_id(current_user, request)` instead.
    Shell always sends `?company_id=N` for the currently selected company.
"""
import os
from datetime import datetime

from flask import Flask, jsonify, request, abort
from flask_login import LoginManager, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, or_

from corper_shared.auth import make_user_loader, make_request_loader, ProxyEmployee
from corper_shared.service_client import CoreClient
from corper_shared.context import active_company_id, require_section

MODULE_NAME = os.environ.get("MODULE_NAME", "mailer")
SECTION = "notifications"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
core = CoreClient(os.environ.get("CORE_REGISTRY_URL", "http://core-registry:5001"))

login_manager = LoginManager(app)
# user_loader — session-based вход (dev-консоль / standalone).
# request_loader — ОБЯЗАТЕЛЬНО для портала: модуль в iframe stateless,
# nginx auth_request кладёт личность в заголовок X-Employee-Id, и читает
# его только request_loader. Без него все @login_required → 401 на портале.
login_manager.user_loader(make_user_loader(core))
login_manager.request_loader(make_request_loader(core, app.config["SECRET_KEY"]))


from models import (  # noqa: E402, F401
    Channel, TelegramGroup, EventType, RoutingRule,
    Message, InboundMessage, PollState,
)
from routing import route_event  # noqa: E402
from delivery_telegram import get_me as tg_get_me, get_chat_member as tg_get_member, TelegramError  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

_PUBLIC_CHANNEL_KINDS = ("email", "telegram")


def _channel_status(c):
    if c is None or not c.is_enabled:
        return "unconfigured"
    if c.last_test_ok is True:
        return "ok"
    if c.last_test_ok is False:
        return "error"
    return "untested"


def _channel_public(c, kind):
    if c is None:
        return {"kind": kind, "is_enabled": False, "label": "",
                "status": "unconfigured", "last_test_at": None}
    return {
        "kind": c.kind,
        "is_enabled": bool(c.is_enabled),
        "label": c.label or "",
        "status": _channel_status(c),
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
    }


def _mask_email_config(cfg):
    safe = dict(cfg or {})
    safe["has_password"] = bool(safe.pop("password", None))
    return safe


def _mask_telegram_config(cfg):
    safe = dict(cfg or {})
    safe["has_bot_token"] = bool(safe.pop("bot_token", None))
    return safe


def _get_or_create_channel(company_id, kind):
    c = Channel.query.filter_by(company_id=company_id, kind=kind).first()
    if c is None:
        c = Channel(company_id=company_id, kind=kind, is_enabled=False, config={})
        db.session.add(c)
        db.session.flush()
    return c


def _channel_full(c):
    return {
        "id": c.id,
        "kind": c.kind,
        "is_enabled": c.is_enabled,
        "label": c.label or "",
        "config": _mask_email_config(c.config or {}) if c.kind == "email"
                  else _mask_telegram_config(c.config or {}),
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        "last_test_ok": c.last_test_ok,
        "last_test_error": c.last_test_error,
    }


def _group_dict(g):
    return {
        "id": g.id, "company_id": g.company_id, "channel_id": g.channel_id,
        "chat_id": g.chat_id, "title": g.title, "chat_type": g.chat_type,
        "branch_id": g.branch_id,
        "is_member": g.is_member, "can_send": g.can_send,
        "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
        "added_at": g.added_at.isoformat() if g.added_at else None,
    }


def _event_type_dict(et):
    return {"id": et.id, "key": et.key, "label": et.label,
            "source_module": et.source_module,
            "created_at": et.created_at.isoformat() if et.created_at else None}


def _rule_dict(r):
    return {
        "id": r.id, "company_id": r.company_id,
        "event_type_id": r.event_type_id, "channel_id": r.channel_id,
        "recipients": r.recipients or {},
        "is_enabled": r.is_enabled, "priority": r.priority,
    }


def _message_dict(m):
    return {
        "id": m.id, "company_id": m.company_id, "channel_id": m.channel_id,
        "source_module": m.source_module, "event_type": m.event_type,
        "to_address": m.to_address, "subject": m.subject,
        "status": m.status, "attempts": m.attempts,
        "last_error": m.last_error,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        "dedup_key": m.dedup_key,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _inbound_dict(i):
    return {
        "id": i.id, "company_id": i.company_id, "channel_id": i.channel_id,
        "chat_id": i.chat_id, "from_user_id": i.from_user_id,
        "from_username": i.from_username, "text": i.text,
        "telegram_message_id": i.telegram_message_id,
        "reply_to_message_id": i.reply_to_message_id,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


def _is_super_admin():
    return getattr(current_user, "portal_role", "") == "super_admin"


# ── /health ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "module": MODULE_NAME}


# ── /channels ─────────────────────────────────────────────────────────────

@app.get("/channels")
@login_required
def list_channels():
    """Inter-service: «какие каналы есть у компании и в каком они состоянии».

    Без секретов — доступно любому залогиненному члену компании.
    """
    company_id = active_company_id(current_user, request)
    rows = {c.kind: c for c in Channel.query.filter_by(company_id=company_id).all()}
    return jsonify([_channel_public(rows.get(k), k) for k in _PUBLIC_CHANNEL_KINDS])


@app.get("/channels/email")
@login_required
def get_email_channel():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    c = Channel.query.filter_by(company_id=company_id, kind="email").first()
    if c is None:
        return jsonify({"kind": "email", "is_enabled": False, "label": "",
                        "config": {"has_password": False},
                        "last_test_at": None, "last_test_ok": None,
                        "last_test_error": None})
    return jsonify(_channel_full(c))


@app.put("/channels/email")
@login_required
def put_email_channel():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    cfg_in = dict(data.get("config") or {})

    c = _get_or_create_channel(company_id, "email")
    if "is_enabled" in data:
        c.is_enabled = bool(data["is_enabled"])
    if "label" in data:
        c.label = str(data.get("label") or "")[:120]

    merged = dict(c.config or {})
    for k in ("host", "port", "use_tls", "username", "sender_name", "sender_email"):
        if k in cfg_in:
            merged[k] = cfg_in[k]
    if "password" in cfg_in:
        pwd = cfg_in.get("password")
        if pwd:
            merged["password"] = pwd
    c.config = merged
    c.last_test_at = None
    c.last_test_ok = None
    c.last_test_error = None
    db.session.commit()
    return jsonify({"id": c.id, "kind": c.kind, "is_enabled": c.is_enabled})


@app.get("/channels/telegram")
@login_required
def get_telegram_channel():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    c = Channel.query.filter_by(company_id=company_id, kind="telegram").first()
    if c is None:
        return jsonify({"kind": "telegram", "is_enabled": False, "label": "",
                        "config": {"has_bot_token": False},
                        "last_test_at": None, "last_test_ok": None,
                        "last_test_error": None})
    return jsonify(_channel_full(c))


@app.put("/channels/telegram")
@login_required
def put_telegram_channel():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    cfg_in = dict(data.get("config") or {})

    c = _get_or_create_channel(company_id, "telegram")
    if "is_enabled" in data:
        c.is_enabled = bool(data["is_enabled"])
    if "label" in data:
        c.label = str(data.get("label") or "")[:120]

    merged = dict(c.config or {})
    for k in ("bot_username", "bot_id"):
        if k in cfg_in:
            merged[k] = cfg_in[k]
    if "bot_token" in cfg_in:
        tok = cfg_in.get("bot_token")
        if tok:
            merged["bot_token"] = tok
    c.config = merged
    c.last_test_at = None
    c.last_test_ok = None
    c.last_test_error = None
    db.session.commit()
    return jsonify({"id": c.id, "kind": c.kind, "is_enabled": c.is_enabled})


# ── /channels/email/test и /bot/check ─────────────────────────────────────

@app.post("/channels/email/test")
@login_required
def email_test():
    """Запрашивает тест-отправку: кладёт в очередь, worker отправит."""
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    to_addr = (data.get("to") or "").strip()
    if not to_addr or "@" not in to_addr:
        return jsonify({"error": "Укажите корректный email в поле to"}), 400

    c = Channel.query.filter_by(company_id=company_id, kind="email").first()
    if c is None or not c.is_enabled:
        return jsonify({"error": "Email-канал не настроен или выключен"}), 400

    m = Message(
        company_id=company_id, channel_id=c.id,
        source_module="_test", event_type="_test.email",
        payload={"requested_by": current_user.id},
        to_address=to_addr,
        subject="Тестовое письмо CORPER",
        body_text=(f"Это тестовое письмо от модуля рассылок CORPER.\n"
                   f"Время запроса: {datetime.utcnow().isoformat()}Z\n"
                   f"Если вы получили это сообщение — SMTP настроен правильно."),
        status="pending",
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({"message_id": m.id, "status": "pending"}), 202


@app.post("/bot/check")
@login_required
def bot_check():
    """Синхронно getMe → автозаполняет bot_id/bot_username, ставит статус."""
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    c = Channel.query.filter_by(company_id=company_id, kind="telegram").first()
    if c is None:
        return jsonify({"error": "Telegram-канал не настроен"}), 400
    cfg = c.config or {}
    if not cfg.get("bot_token"):
        return jsonify({"error": "bot_token не задан"}), 400
    try:
        info = tg_get_me(cfg["bot_token"])
    except TelegramError as e:
        c.last_test_at = datetime.utcnow()
        c.last_test_ok = False
        c.last_test_error = str(e)
        db.session.commit()
        return jsonify({"ok": False, "error": str(e)}), 200
    cfg["bot_id"] = info.get("id")
    cfg["bot_username"] = info.get("username")
    c.config = dict(cfg)
    c.last_test_at = datetime.utcnow()
    c.last_test_ok = True
    c.last_test_error = None
    db.session.commit()
    return jsonify({"ok": True, "bot_id": info.get("id"),
                    "bot_username": info.get("username"),
                    "first_name": info.get("first_name")}), 200


# ── /groups ───────────────────────────────────────────────────────────────

@app.get("/groups")
@login_required
def list_groups():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    rows = (TelegramGroup.query
            .filter_by(company_id=company_id)
            .order_by(TelegramGroup.added_at.desc()).all())
    return jsonify([_group_dict(g) for g in rows])


@app.post("/groups")
@login_required
def create_group():
    """Ручное добавление — для случаев, когда не хочется ждать polling."""
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    chat_id = data.get("chat_id")
    if chat_id is None:
        return jsonify({"error": "chat_id обязателен"}), 400
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return jsonify({"error": "chat_id должен быть числом"}), 400

    c = Channel.query.filter_by(company_id=company_id, kind="telegram").first()
    if c is None:
        return jsonify({"error": "Сначала настройте Telegram-канал"}), 400

    existing = TelegramGroup.query.filter_by(
        company_id=company_id, chat_id=chat_id).first()
    if existing is not None:
        return jsonify({"error": "Такая группа уже есть", "id": existing.id}), 409

    g = TelegramGroup(
        company_id=company_id, channel_id=c.id, chat_id=chat_id,
        title=str(data.get("title") or "")[:255],
        chat_type=data.get("chat_type") or "group",
        branch_id=data.get("branch_id"),
        is_member=False, can_send=False,
    )
    db.session.add(g)
    db.session.commit()
    return jsonify(_group_dict(g)), 201


@app.put("/groups/<int:gid>")
@login_required
def update_group(gid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    g = TelegramGroup.query.filter_by(id=gid, company_id=company_id).first_or_404()
    data = request.get_json(force=True) or {}
    if "title" in data:
        g.title = str(data.get("title") or "")[:255]
    if "branch_id" in data:
        bid = data.get("branch_id")
        g.branch_id = int(bid) if bid is not None else None
    db.session.commit()
    return jsonify(_group_dict(g))


@app.delete("/groups/<int:gid>")
@login_required
def delete_group(gid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    g = TelegramGroup.query.filter_by(id=gid, company_id=company_id).first_or_404()
    db.session.delete(g)
    db.session.commit()
    return jsonify({"ok": True})


@app.post("/groups/<int:gid>/check")
@login_required
def check_group(gid):
    """Синхронно проверить членство бота в чате."""
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    g = TelegramGroup.query.filter_by(id=gid, company_id=company_id).first_or_404()
    ch = Channel.query.get(g.channel_id)
    if ch is None:
        return jsonify({"error": "Канал не найден"}), 400
    cfg = ch.config or {}
    bot_token = cfg.get("bot_token")
    bot_id = cfg.get("bot_id")
    if not bot_token or not bot_id:
        return jsonify({"error": "Bot не проверен (нажмите «Проверить бота» сначала)"}), 400
    try:
        info = tg_get_member(bot_token, g.chat_id, int(bot_id))
    except TelegramError as e:
        g.is_member = False
        g.can_send = False
        g.last_seen_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"ok": False, "error": str(e), **_group_dict(g)}), 200
    status = (info or {}).get("status") or ""
    g.is_member = status in ("creator", "administrator", "member")
    g.can_send = status in ("creator", "administrator") or (
        status == "member" and info.get("can_send_messages") is not False)
    g.last_seen_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "tg_status": status, **_group_dict(g)})


# ── /event-types ──────────────────────────────────────────────────────────

@app.get("/event-types")
@login_required
def list_event_types():
    """Каталог событий. Глобальный (не per-company) — события общие для всех."""
    company_id = active_company_id(current_user, request)
    # check только view — каталог нужен на странице «Правила»
    require_section(current_user, company_id, SECTION, core, "view")
    src = request.args.get("source_module")
    q = EventType.query
    if src:
        q = q.filter_by(source_module=src)
    rows = q.order_by(EventType.source_module.asc(), EventType.key.asc()).all()
    return jsonify([_event_type_dict(et) for et in rows])


@app.post("/event-types/sync")
def sync_event_types():
    """Вызывается deploy-agent'ом после деплоя модуля с emits в module.json.

    Авторизация: внутренний вызов от deploy-agent — приходит с X-Employee-Id
    (deploy-agent сервисный аккаунт). Требуем super_admin.

    Body: {source_module: "...", events: [{event_type, label}, ...]}
    """
    eid_header = request.headers.get("X-Employee-Id")
    if not eid_header:
        return jsonify({"error": "X-Employee-Id required"}), 401
    try:
        # синхронно перезагружаем сотрудника через CoreClient,
        # потому что request_loader уже Сделал это; current_user должен быть OK
        if not getattr(current_user, "is_authenticated", False):
            return jsonify({"error": "unauthorized"}), 401
        if not _is_super_admin():
            return jsonify({"error": "super_admin required"}), 403
    except Exception:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True) or {}
    source_module = (data.get("source_module") or "").strip()
    events = data.get("events") or []
    if not source_module:
        return jsonify({"error": "source_module required"}), 400

    upserted = 0
    for ev in events:
        key = (ev.get("event_type") or "").strip()
        if not key:
            continue
        label = ev.get("label") or key
        et = EventType.query.filter_by(key=key).first()
        if et is None:
            et = EventType(key=key, label=label, source_module=source_module)
            db.session.add(et)
        else:
            et.label = label
            et.source_module = source_module
        upserted += 1
    db.session.commit()
    return jsonify({"ok": True, "upserted": upserted})


# ── /rules ────────────────────────────────────────────────────────────────

@app.get("/rules")
@login_required
def list_rules():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    rows = (RoutingRule.query
            .filter_by(company_id=company_id)
            .order_by(RoutingRule.priority.asc(), RoutingRule.id.asc()).all())
    return jsonify([_rule_dict(r) for r in rows])


@app.post("/rules")
@login_required
def create_rule():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    if not data.get("event_type_id") or not data.get("channel_id"):
        return jsonify({"error": "event_type_id и channel_id обязательны"}), 400
    # Валидация принадлежности канала компании
    ch = Channel.query.get(int(data["channel_id"]))
    if ch is None or ch.company_id != company_id:
        return jsonify({"error": "channel_id не принадлежит компании"}), 400

    r = RoutingRule(
        company_id=company_id,
        event_type_id=int(data["event_type_id"]),
        channel_id=int(data["channel_id"]),
        recipients=data.get("recipients") or {},
        is_enabled=bool(data.get("is_enabled", True)),
        priority=int(data.get("priority") or 100),
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(_rule_dict(r)), 201


@app.put("/rules/<int:rid>")
@login_required
def update_rule(rid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    r = RoutingRule.query.filter_by(id=rid, company_id=company_id).first_or_404()
    data = request.get_json(force=True) or {}
    if "channel_id" in data:
        ch = Channel.query.get(int(data["channel_id"]))
        if ch is None or ch.company_id != company_id:
            return jsonify({"error": "channel_id не принадлежит компании"}), 400
        r.channel_id = int(data["channel_id"])
    if "event_type_id" in data:
        r.event_type_id = int(data["event_type_id"])
    if "recipients" in data:
        r.recipients = data["recipients"] or {}
    if "is_enabled" in data:
        r.is_enabled = bool(data["is_enabled"])
    if "priority" in data:
        r.priority = int(data["priority"])
    db.session.commit()
    return jsonify(_rule_dict(r))


@app.delete("/rules/<int:rid>")
@login_required
def delete_rule(rid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    r = RoutingRule.query.filter_by(id=rid, company_id=company_id).first_or_404()
    db.session.delete(r)
    db.session.commit()
    return jsonify({"ok": True})


# ── /events ───────────────────────────────────────────────────────────────

@app.post("/events")
@login_required
def receive_event():
    """Inter-service: модули-источники постят сюда события. Routing engine
    создаёт mailer.message(pending) для каждого получателя по матчу правил."""
    data = request.get_json(force=True) or {}
    try:
        company_id = int(data.get("company_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "company_id required"}), 400
    event_type_key = (data.get("event_type") or "").strip()
    source_module = (data.get("source_module") or "unknown").strip()
    if not event_type_key:
        return jsonify({"error": "event_type required"}), 400

    # Любой залогиненный member компании может постить события от имени своего
    # модуля. Реальное членство проверим: либо admin-bypass, либо company ∈
    # current_user.company_ids
    if not _is_super_admin():
        cids = getattr(current_user, "_data", {}).get("company_ids") or []
        if company_id not in cids and getattr(current_user, "portal_role", "") != "admin":
            return jsonify({"error": "company access denied"}), 403

    result = route_event(
        db=db, core_client=core,
        Channel=Channel, RoutingRule=RoutingRule, EventType=EventType,
        Message=Message, TelegramGroup=TelegramGroup,
        company_id=company_id,
        source_module=source_module,
        event_type_key=event_type_key,
        payload=data.get("payload") or {},
        branch_id=data.get("branch_id"),
        dedup_key=data.get("dedup_key"),
    )
    code = 202 if result.get("message_ids") else 200
    return jsonify(result), code


# ── /messages, /inbound (журнал, read-only) ───────────────────────────────

def _parse_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@app.get("/messages")
@login_required
def list_messages():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    limit = max(1, min(_parse_int(request.args.get("limit"), 50) or 50, 200))
    status = request.args.get("status")
    kind = request.args.get("kind")
    since_id = _parse_int(request.args.get("since_id"), None)

    q = Message.query.filter_by(company_id=company_id)
    if status:
        q = q.filter(Message.status == status)
    if kind:
        q = q.join(Channel, Channel.id == Message.channel_id).filter(Channel.kind == kind)
    if since_id:
        q = q.filter(Message.id < since_id)
    rows = q.order_by(Message.id.desc()).limit(limit).all()
    return jsonify({"items": [_message_dict(m) for m in rows],
                    "next_since_id": rows[-1].id if len(rows) == limit else None})


@app.get("/inbound")
@login_required
def list_inbound():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    limit = max(1, min(_parse_int(request.args.get("limit"), 50) or 50, 200))
    since_id = _parse_int(request.args.get("since_id"), None)
    q = InboundMessage.query.filter_by(company_id=company_id)
    if since_id:
        q = q.filter(InboundMessage.id < since_id)
    rows = q.order_by(InboundMessage.id.desc()).limit(limit).all()
    return jsonify({"items": [_inbound_dict(i) for i in rows],
                    "next_since_id": rows[-1].id if len(rows) == limit else None})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
