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
from sqlalchemy.orm.attributes import flag_modified

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
    Channel, TelegramGroup, TelegramTopic, TopicRegistration,
    EventType, RoutingRule,
    Message, InboundMessage, PollState,
)
from routing import route_event_via_rules, deliver_explicit  # noqa: E402
from delivery_telegram import (  # noqa: E402
    get_me as tg_get_me,
    get_chat_member as tg_get_member,
    get_my_name, get_my_description, get_my_short_description, get_my_commands,
    set_my_name, set_my_description, set_my_short_description, set_my_commands,
    TelegramError,
)
import secrets as _secrets
from datetime import timedelta


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
        "is_forum": g.is_forum,
        "branch_id": g.branch_id,
        "department_id": g.department_id,
        "is_member": g.is_member, "can_send": g.can_send,
        "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
        "added_at": g.added_at.isoformat() if g.added_at else None,
        "archived_at": g.archived_at.isoformat() if g.archived_at else None,
    }


def _event_type_dict(et):
    return {"id": et.id, "key": et.key, "label": et.label,
            "source_module": et.source_module,
            "created_at": et.created_at.isoformat() if et.created_at else None}


def _rule_dict(r):
    return {
        "id": r.id, "company_id": r.company_id,
        "event_type_id": r.event_type_id,
        "branch_id": r.branch_id,
        "telegram_group_id": r.telegram_group_id,
        "topic_id": r.topic_id,
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
    # SQLAlchemy не отслеживает in-place мутацию JSONB по умолчанию;
    # без flag_modified изменения cfg не попадают в COMMIT — баг: после
    # успешного getMe bot_id/username возвращались в response, но в БД
    # не сохранялись, и фронт после await load() видел пустые поля.
    new_cfg = dict(cfg)
    new_cfg["bot_id"] = info.get("id")
    new_cfg["bot_username"] = info.get("username")
    c.config = new_cfg
    flag_modified(c, "config")
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
    include_archived = request.args.get("include_archived") in ("1", "true")
    q = TelegramGroup.query.filter_by(company_id=company_id)
    if not include_archived:
        q = q.filter(TelegramGroup.archived_at.is_(None))
    rows = q.order_by(TelegramGroup.added_at.desc()).all()
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
        # idempotent: возвращаем существующую (восстанавливаем из архива если нужно)
        if existing.archived_at is not None:
            existing.archived_at = None
            db.session.commit()
        return jsonify(_group_dict(existing)), 200

    g = TelegramGroup(
        company_id=company_id, channel_id=c.id, chat_id=chat_id,
        title=str(data.get("title") or "")[:255],
        chat_type=data.get("chat_type") or "group",
        branch_id=data.get("branch_id"),
        department_id=data.get("department_id"),
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


def _validate_rule_payload(data: dict, company_id: int) -> tuple[dict, dict | None]:
    """Возвращает (clean_fields, error_dict). error=None если всё ок.

    Новая схема правила (TG-only):
      event_type_id (FK), branch_id (nullable), telegram_group_id (FK),
      topic_id (nullable FK), is_enabled, priority.
    """
    out: dict = {}
    if "event_type_id" in data:
        et = EventType.query.get(int(data["event_type_id"] or 0))
        if et is None:
            return out, {"error": "event_type не найден"}
        out["event_type_id"] = et.id
    if "telegram_group_id" in data:
        gid = int(data["telegram_group_id"] or 0)
        g = TelegramGroup.query.filter_by(id=gid, company_id=company_id).first()
        if g is None:
            return out, {"error": "telegram_group_id не принадлежит компании"}
        out["telegram_group_id"] = g.id
    if "branch_id" in data:
        bid = data.get("branch_id")
        out["branch_id"] = int(bid) if bid not in (None, "") else None
    if "topic_id" in data:
        tid = data.get("topic_id")
        if tid in (None, ""):
            out["topic_id"] = None
        else:
            t = TelegramTopic.query.filter_by(id=int(tid),
                                              company_id=company_id).first()
            if t is None:
                return out, {"error": "topic_id не принадлежит компании"}
            out["topic_id"] = t.id
    if "is_enabled" in data:
        out["is_enabled"] = bool(data["is_enabled"])
    if "priority" in data:
        out["priority"] = int(data["priority"] or 100)
    return out, None


@app.post("/rules")
@login_required
def create_rule():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    if not data.get("event_type_id") or not data.get("telegram_group_id"):
        return jsonify({"error": "event_type_id и telegram_group_id обязательны"}), 400
    clean, err = _validate_rule_payload(data, company_id)
    if err:
        return jsonify(err), 400

    r = RoutingRule(
        company_id=company_id,
        event_type_id=clean["event_type_id"],
        branch_id=clean.get("branch_id"),
        telegram_group_id=clean["telegram_group_id"],
        topic_id=clean.get("topic_id"),
        is_enabled=clean.get("is_enabled", True),
        priority=clean.get("priority", 100),
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
    clean, err = _validate_rule_payload(data, company_id)
    if err:
        return jsonify(err), 400
    for k, v in clean.items():
        setattr(r, k, v)
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
    """Inter-service: модули-источники постят сюда события.

    Два режима (диспатч по полям):
      • если задан `channel_kind` ИЛИ непустой `recipients` →
        `deliver_explicit` (модуль сам выбрал кому/как);
      • иначе → `route_event_via_rules` (TG-only через правила
        с фильтром по `branch_id`).
    """
    data = request.get_json(force=True) or {}
    try:
        company_id = int(data.get("company_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "company_id required"}), 400
    event_type_key = (data.get("event_type") or "").strip()
    source_module = (data.get("source_module") or "unknown").strip()
    if not event_type_key:
        return jsonify({"error": "event_type required"}), 400

    # Company-access check (admin bypass)
    if not _is_super_admin():
        cids = getattr(current_user, "_data", {}).get("company_ids") or []
        if company_id not in cids and getattr(current_user, "portal_role", "") != "admin":
            return jsonify({"error": "company access denied"}), 403

    channel_kind = (data.get("channel_kind") or "").strip().lower()
    recipients = data.get("recipients") or {}
    is_explicit = bool(channel_kind) or any(recipients.values()) if isinstance(recipients, dict) else False

    if is_explicit:
        if not channel_kind:
            channel_kind = "email" if any(k in recipients for k in
                                          ("emails", "employee_ids", "branch_ids")) else "telegram"
        result = deliver_explicit(
            db=db, core_client=core,
            Channel=Channel, EventType=EventType,
            Message=Message, TelegramGroup=TelegramGroup,
            company_id=company_id,
            source_module=source_module,
            event_type_key=event_type_key,
            channel_kind=channel_kind,
            recipients=recipients,
            subject=data.get("subject"),
            body_text=data.get("body_text"),
            body_html=data.get("body_html"),
            payload=data.get("payload") or {},
            parse_mode=data.get("parse_mode"),
            dedup_key=data.get("dedup_key"),
        )
    else:
        result = route_event_via_rules(
            db=db,
            Channel=Channel, RoutingRule=RoutingRule, EventType=EventType,
            Message=Message, TelegramGroup=TelegramGroup,
            TelegramTopic=TelegramTopic,
            company_id=company_id,
            source_module=source_module,
            event_type_key=event_type_key,
            branch_id=data.get("branch_id"),
            subject=data.get("subject"),
            body_text=data.get("body_text"),
            body_html=data.get("body_html"),
            payload=data.get("payload") or {},
            dedup_key=data.get("dedup_key"),
        )

    if result.get("error"):
        return jsonify(result), 400
    code = 202 if result.get("message_ids") else 200
    return jsonify(result), code


# ── /bot/branding ─────────────────────────────────────────────────────────

@app.get("/bot/branding")
@login_required
def get_bot_branding():
    """Подтянуть текущие name/description/short_description/commands из Bot API."""
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    c = Channel.query.filter_by(company_id=company_id, kind="telegram").first()
    if c is None or not (c.config or {}).get("bot_token"):
        return jsonify({"error": "bot_token не задан"}), 400
    token = c.config["bot_token"]
    out = {"name": "", "description": "", "short_description": "", "commands": []}
    errors = []
    for key, fn in (("name", get_my_name),
                    ("description", get_my_description),
                    ("short_description", get_my_short_description)):
        try:
            res = fn(token)
            out[key] = (res or {}).get(key) or ""
        except TelegramError as e:
            errors.append(f"{key}: {e}")
    try:
        out["commands"] = get_my_commands(token)
    except TelegramError as e:
        errors.append(f"commands: {e}")
    if errors:
        out["_errors"] = errors
    return jsonify(out)


@app.put("/bot/branding")
@login_required
def put_bot_branding():
    """Установить непустые поля через Bot API (set_my_*)."""
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    c = Channel.query.filter_by(company_id=company_id, kind="telegram").first()
    if c is None or not (c.config or {}).get("bot_token"):
        return jsonify({"error": "bot_token не задан"}), 400
    token = c.config["bot_token"]
    data = request.get_json(force=True) or {}
    applied: list[str] = []
    errors: list[str] = []

    def _try(field: str, fn, *args):
        try:
            fn(token, *args)
            applied.append(field)
        except TelegramError as e:
            errors.append(f"{field}: {e}")

    if "name" in data:
        _try("name", set_my_name, str(data.get("name") or "")[:64])
    if "description" in data:
        _try("description", set_my_description, str(data.get("description") or "")[:512])
    if "short_description" in data:
        _try("short_description", set_my_short_description,
             str(data.get("short_description") or "")[:120])
    if "commands" in data:
        cmds = data.get("commands") or []
        # клиент кладёт list[{command, description}]; нормализуем
        norm = []
        for cmd in cmds:
            if not isinstance(cmd, dict): continue
            c_name = (cmd.get("command") or "").strip().lstrip("/")
            c_desc = (cmd.get("description") or "").strip()
            if c_name and c_desc:
                norm.append({"command": c_name[:32], "description": c_desc[:256]})
        _try("commands", set_my_commands, norm)
    return jsonify({"ok": not errors, "applied": applied, "errors": errors})


# ── /topics + /topic-registrations ────────────────────────────────────────

def _topic_dict(t):
    return {
        "id": t.id, "group_id": t.group_id,
        "telegram_thread_id": t.telegram_thread_id,
        "name": t.name,
        "registered_at": t.registered_at.isoformat() if t.registered_at else None,
    }


@app.get("/groups/<int:gid>/topics")
@login_required
def list_group_topics(gid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    g = TelegramGroup.query.filter_by(id=gid, company_id=company_id).first_or_404()
    rows = (TelegramTopic.query
            .filter_by(group_id=g.id, archived_at=None)
            .order_by(TelegramTopic.name.asc()).all())
    return jsonify([_topic_dict(t) for t in rows])


# Список существительных для seed-фразы — читаемо + неконфликтно.
_PHRASE_WORDS = (
    "LIME RAY SAGE INK MINT JADE PEAK FROG BIRD KOI "
    "OAK FOX OWL ELK WOLF CRANE LARK SWAN STAR MOON "
    "RIVER LAKE SAND DUNE PINE FERN MAPLE PETAL CLOVER "
    "CORAL AMBER PEARL OPAL TOPAZ FLINT NOVA NEBULA"
).split()


def _generate_phrase() -> str:
    """`TOPIC-LIME-4Q7K-2026` — TTL и сама фраза удобочитаемы."""
    word = _secrets.choice(_PHRASE_WORDS)
    salt = _secrets.token_hex(2).upper()  # 4 hex символа
    year = datetime.utcnow().year
    return f"TOPIC-{word}-{salt}-{year}"


def _topic_reg_dict(p):
    """Pending-registration dict — работает для обоих режимов:

      • topic-binding (изначально group_id != NULL): на consume topic_id
        указывает на созданный TelegramTopic;
      • group-binding (изначально group_id IS NULL → ставится на consume):
        на consume group_id указывает на созданную TelegramGroup, topic_id NULL.
    """
    is_group_mode = p.topic_id is None and p.consumed_at is not None
    out = {
        "id": p.id, "phrase": p.phrase, "name": p.name,
        "mode": "group" if (p.group_id is None and not p.consumed_at) or is_group_mode else "topic",
        "group_id_target": p.group_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "consumed_at": p.consumed_at.isoformat() if p.consumed_at else None,
        "topic": _topic_dict(TelegramTopic.query.get(p.topic_id)) if p.topic_id else None,
        "group": None,
    }
    if is_group_mode and p.group_id:
        g = TelegramGroup.query.get(p.group_id)
        if g is not None:
            out["group"] = _group_dict(g)
    return out


@app.post("/groups/<int:gid>/topic-registrations")
@login_required
def create_topic_registration(gid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    g = TelegramGroup.query.filter_by(id=gid, company_id=company_id).first_or_404()
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()[:255] or None
    # уникальный phrase (retry на маловероятную коллизию)
    for _ in range(5):
        phrase = _generate_phrase()
        if not TopicRegistration.query.filter_by(phrase=phrase).first():
            break
    else:
        return jsonify({"error": "phrase collision"}), 500
    p = TopicRegistration(
        company_id=company_id, group_id=g.id,
        phrase=phrase, name=name,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(_topic_reg_dict(p)), 201


@app.get("/topic-registrations/<int:pid>")
@login_required
def get_topic_registration(pid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    p = TopicRegistration.query.filter_by(id=pid, company_id=company_id).first_or_404()
    return jsonify(_topic_reg_dict(p))


# ── /groups/registrations — seed-привязка САМОЙ группы ──────────────────
# Альтернатива ручному chat_id-вводу: бот должен быть в чате, юзер копирует
# фразу из UI в любое сообщение чата → бот распознаёт → регистрирует группу
# с chat_id из msg.chat.id.

@app.post("/groups/registrations")
@login_required
def create_group_registration():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()[:255] or None
    for _ in range(5):
        phrase = _generate_phrase()
        if not TopicRegistration.query.filter_by(phrase=phrase).first():
            break
    else:
        return jsonify({"error": "phrase collision"}), 500
    p = TopicRegistration(
        company_id=company_id, group_id=None,   # NULL → group-binding mode
        phrase=phrase, name=name,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(_topic_reg_dict(p)), 201


@app.get("/groups/registrations/<int:pid>")
@login_required
def get_group_registration(pid):
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    p = TopicRegistration.query.filter_by(id=pid, company_id=company_id).first_or_404()
    return jsonify(_topic_reg_dict(p))


# ── /admin/* — системный канал (super_admin only, company_id IS NULL) ─────

def _admin_or_403():
    if not _is_super_admin():
        return jsonify({"error": "super_admin required"}), 403
    return None


def _get_or_create_system_channel(kind: str):
    """company_id IS NULL → системный канал. Один на kind."""
    c = Channel.query.filter(Channel.company_id.is_(None),
                             Channel.kind == kind).first()
    if c is None:
        c = Channel(company_id=None, kind=kind, is_enabled=False, config={})
        db.session.add(c)
        db.session.flush()
    return c


def _system_channel_payload(c):
    """View с маскированным секретом — для GET /admin/channels/<kind>."""
    if c is None:
        return {"kind": None, "is_enabled": False, "label": "",
                "config": {},
                "last_test_at": None, "last_test_ok": None, "last_test_error": None}
    cfg = _mask_email_config(c.config or {}) if c.kind == "email" else _mask_telegram_config(c.config or {})
    return {
        "kind": c.kind,
        "is_enabled": c.is_enabled,
        "label": c.label or "",
        "config": cfg,
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        "last_test_ok": c.last_test_ok,
        "last_test_error": c.last_test_error,
    }


@app.get("/admin/channels")
@login_required
def admin_list_channels():
    err = _admin_or_403()
    if err: return err
    rows = {c.kind: c for c in
            Channel.query.filter(Channel.company_id.is_(None)).all()}
    return jsonify([_channel_public(rows.get(k), k) for k in _PUBLIC_CHANNEL_KINDS])


@app.get("/admin/channels/<kind>")
@login_required
def admin_get_channel(kind):
    err = _admin_or_403()
    if err: return err
    if kind not in ("email", "telegram"):
        return jsonify({"error": "unknown kind"}), 400
    c = Channel.query.filter(Channel.company_id.is_(None),
                             Channel.kind == kind).first()
    return jsonify(_system_channel_payload(c))


@app.put("/admin/channels/<kind>")
@login_required
def admin_put_channel(kind):
    err = _admin_or_403()
    if err: return err
    if kind not in ("email", "telegram"):
        return jsonify({"error": "unknown kind"}), 400
    data = request.get_json(force=True) or {}
    cfg_in = dict(data.get("config") or {})
    c = _get_or_create_system_channel(kind)
    if "is_enabled" in data:
        c.is_enabled = bool(data["is_enabled"])
    if "label" in data:
        c.label = str(data.get("label") or "")[:120]
    old_cfg = dict(c.config or {})
    merged = dict(old_cfg)
    # Поля, изменение которых инвалидирует предыдущий getMe / SMTP-тест.
    # Если эти ключи в PUT идентичны тому, что в БД (или просто не пришли),
    # last_test_* сохраняем — иначе пользователь жалуется «после Save
    # значок 'Не проверен', хотя только что Проверял».
    if kind == "email":
        sensitive_keys = ("host", "port", "use_tls", "username", "sender_email")
        for k in ("host", "port", "use_tls", "username", "sender_name", "sender_email"):
            if k in cfg_in:
                merged[k] = cfg_in[k]
        if "password" in cfg_in and cfg_in.get("password"):
            merged["password"] = cfg_in["password"]
    else:  # telegram
        sensitive_keys = ()  # для TG только bot_token, проверяется отдельно
        for k in ("bot_username", "bot_id"):
            if k in cfg_in:
                merged[k] = cfg_in[k]
        if "bot_token" in cfg_in and cfg_in.get("bot_token"):
            merged["bot_token"] = cfg_in["bot_token"]
    c.config = merged
    flag_modified(c, "config")
    # Detect whether secrets/credentials actually changed.
    creds_changed = False
    if kind == "email":
        for k in sensitive_keys:
            if old_cfg.get(k) != merged.get(k):
                creds_changed = True; break
        if not creds_changed and cfg_in.get("password"):  # пришёл новый пароль
            creds_changed = True
    else:  # telegram
        if cfg_in.get("bot_token") and cfg_in["bot_token"] != old_cfg.get("bot_token"):
            creds_changed = True
    if creds_changed:
        c.last_test_at = None
        c.last_test_ok = None
        c.last_test_error = None
    db.session.commit()
    return jsonify({"id": c.id, "kind": c.kind, "is_enabled": c.is_enabled})


@app.post("/admin/channels/email/test")
@login_required
def admin_email_test():
    err = _admin_or_403()
    if err: return err
    data = request.get_json(force=True) or {}
    to_addr = (data.get("to") or "").strip()
    if not to_addr or "@" not in to_addr:
        return jsonify({"error": "Укажите корректный email"}), 400
    c = Channel.query.filter(Channel.company_id.is_(None),
                             Channel.kind == "email").first()
    if c is None or not c.is_enabled:
        return jsonify({"error": "Системный email не настроен"}), 400
    m = Message(
        company_id=None, channel_id=c.id,
        source_module="_system", event_type="_test.email",
        payload={"requested_by": current_user.id},
        to_address=to_addr,
        subject="Тестовое письмо CORPER (system)",
        body_text=(f"Это тестовое письмо системного канала CORPER.\n"
                   f"Время: {datetime.utcnow().isoformat()}Z\n"),
        status="pending",
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({"message_id": m.id, "status": "pending"}), 202


@app.post("/admin/bot/check")
@login_required
def admin_bot_check():
    err = _admin_or_403()
    if err: return err
    c = Channel.query.filter(Channel.company_id.is_(None),
                             Channel.kind == "telegram").first()
    if c is None:
        return jsonify({"error": "Системный Telegram-канал не настроен"}), 400
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
    # SQLAlchemy не отслеживает in-place мутацию JSONB по умолчанию;
    # без flag_modified изменения cfg не попадают в COMMIT — баг: после
    # успешного getMe bot_id/username возвращались в response, но в БД
    # не сохранялись, и фронт после await load() видел пустые поля.
    new_cfg = dict(cfg)
    new_cfg["bot_id"] = info.get("id")
    new_cfg["bot_username"] = info.get("username")
    c.config = new_cfg
    flag_modified(c, "config")
    c.last_test_at = datetime.utcnow()
    c.last_test_ok = True
    c.last_test_error = None
    db.session.commit()
    return jsonify({"ok": True, "bot_id": info.get("id"),
                    "bot_username": info.get("username"),
                    "first_name": info.get("first_name")}), 200


@app.get("/admin/bot/branding")
@login_required
def admin_get_bot_branding():
    err = _admin_or_403()
    if err: return err
    c = Channel.query.filter(Channel.company_id.is_(None),
                             Channel.kind == "telegram").first()
    if c is None or not (c.config or {}).get("bot_token"):
        return jsonify({"error": "bot_token не задан"}), 400
    token = c.config["bot_token"]
    out = {"name": "", "description": "", "short_description": "", "commands": []}
    errors = []
    for key, fn in (("name", get_my_name),
                    ("description", get_my_description),
                    ("short_description", get_my_short_description)):
        try:
            res = fn(token)
            out[key] = (res or {}).get(key) or ""
        except TelegramError as e:
            errors.append(f"{key}: {e}")
    try:
        out["commands"] = get_my_commands(token)
    except TelegramError as e:
        errors.append(f"commands: {e}")
    if errors:
        out["_errors"] = errors
    return jsonify(out)


@app.put("/admin/bot/branding")
@login_required
def admin_put_bot_branding():
    err = _admin_or_403()
    if err: return err
    c = Channel.query.filter(Channel.company_id.is_(None),
                             Channel.kind == "telegram").first()
    if c is None or not (c.config or {}).get("bot_token"):
        return jsonify({"error": "bot_token не задан"}), 400
    token = c.config["bot_token"]
    data = request.get_json(force=True) or {}
    applied: list[str] = []
    errors: list[str] = []
    def _try(field, fn, *args):
        try: fn(token, *args); applied.append(field)
        except TelegramError as e: errors.append(f"{field}: {e}")
    if "name" in data:
        _try("name", set_my_name, str(data.get("name") or "")[:64])
    if "description" in data:
        _try("description", set_my_description, str(data.get("description") or "")[:512])
    if "short_description" in data:
        _try("short_description", set_my_short_description,
             str(data.get("short_description") or "")[:120])
    if "commands" in data:
        cmds = data.get("commands") or []
        norm = []
        for cmd in cmds:
            if not isinstance(cmd, dict): continue
            cn = (cmd.get("command") or "").strip().lstrip("/")
            cd = (cmd.get("description") or "").strip()
            if cn and cd:
                norm.append({"command": cn[:32], "description": cd[:256]})
        _try("commands", set_my_commands, norm)
    return jsonify({"ok": not errors, "applied": applied, "errors": errors})


# ── /groups/by-dept (inter-service: вызывает core-registry при toggle) ────

@app.post("/groups/by-dept")
@login_required
def upsert_group_by_dept():
    """Inter-service: core-registry зовёт при включении `is_telegram_group=true`
    в Структуре. Создаёт или восстанавливает группу для department_id."""
    if not _is_super_admin():
        return jsonify({"error": "super_admin required"}), 403
    data = request.get_json(force=True) or {}
    try:
        company_id = int(data["company_id"])
        department_id = int(data["department_id"])
        chat_id = int(data["chat_id"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "company_id, department_id, chat_id обязательны"}), 400
    title = str(data.get("title") or "")[:255]

    ch = Channel.query.filter_by(company_id=company_id, kind="telegram").first()
    if ch is None:
        # Канала ещё нет — создадим пустой (admin позже сконфигурирует bot_token)
        ch = Channel(company_id=company_id, kind="telegram",
                     is_enabled=False, config={})
        db.session.add(ch)
        db.session.flush()

    g = TelegramGroup.query.filter_by(company_id=company_id,
                                      chat_id=chat_id).first()
    if g is None:
        g = TelegramGroup(
            company_id=company_id, channel_id=ch.id, chat_id=chat_id,
            title=title or f"Dept #{department_id}",
            chat_type="group", department_id=department_id,
            is_member=False, can_send=False,
        )
        db.session.add(g)
    else:
        g.department_id = department_id
        if title:
            g.title = title
        g.archived_at = None  # restore из архива
    db.session.commit()
    return jsonify(_group_dict(g)), 200


@app.put("/groups/by-dept/<int:did>/archive")
@login_required
def archive_group_by_dept(did):
    """Inter-service: при выключении `is_telegram_group=false` в Структуре."""
    if not _is_super_admin():
        return jsonify({"error": "super_admin required"}), 403
    rows = TelegramGroup.query.filter_by(department_id=did,
                                         archived_at=None).all()
    for g in rows:
        g.archived_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"archived": [g.id for g in rows]})


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


# ── /admin/messages, /admin/inbound, /admin/events — system журнал ────────
# Те же таблицы, что и company-scope, но company_id IS NULL и super_admin
# guard. Используется AdminNotificationsPage для отображения «Системных
# событий» (письма активации, magic-link, регистрации, входящие TG-сообщения
# в системного бота). Возвращают тот же формат, что /messages, /inbound.

@app.get("/admin/messages")
@login_required
def admin_list_messages():
    err = _admin_or_403()
    if err: return err
    limit = max(1, min(_parse_int(request.args.get("limit"), 50) or 50, 200))
    status = request.args.get("status")
    kind = request.args.get("kind")
    source_module = request.args.get("source_module")
    since_id = _parse_int(request.args.get("since_id"), None)
    q = Message.query.filter(Message.company_id.is_(None))
    if status:
        q = q.filter(Message.status == status)
    if kind:
        q = q.join(Channel, Channel.id == Message.channel_id).filter(Channel.kind == kind)
    if source_module:
        q = q.filter(Message.source_module == source_module)
    if since_id:
        q = q.filter(Message.id < since_id)
    rows = q.order_by(Message.id.desc()).limit(limit).all()
    return jsonify({"items": [_message_dict(m) for m in rows],
                    "next_since_id": rows[-1].id if len(rows) == limit else None})


@app.get("/admin/inbound")
@login_required
def admin_list_inbound():
    err = _admin_or_403()
    if err: return err
    limit = max(1, min(_parse_int(request.args.get("limit"), 50) or 50, 200))
    since_id = _parse_int(request.args.get("since_id"), None)
    q = InboundMessage.query.filter(InboundMessage.company_id.is_(None))
    if since_id:
        q = q.filter(InboundMessage.id < since_id)
    rows = q.order_by(InboundMessage.id.desc()).limit(limit).all()
    return jsonify({"items": [_inbound_dict(i) for i in rows],
                    "next_since_id": rows[-1].id if len(rows) == limit else None})


@app.get("/admin/events")
@login_required
def admin_list_events():
    """Объединённый журнал системных событий — outbound (Message)
    + inbound (InboundMessage). Возвращает массив, отсортированный
    по created_at DESC, с дискриминатором `direction`: 'outbound'|'inbound'.

    Это удобный single-feed-источник для UI-таблицы «Системные события»:
    пользователь видит всё подряд (письма + TG-сообщения), фильтрует
    по `direction`, `status`, `kind`, `source_module`, `from`, `to`.
    """
    err = _admin_or_403()
    if err: return err
    limit = max(1, min(_parse_int(request.args.get("limit"), 50) or 50, 200))
    direction = request.args.get("direction")          # 'outbound'|'inbound'|None
    status = request.args.get("status")
    kind = request.args.get("kind")                    # 'email'|'telegram'
    source_module = request.args.get("source_module")

    items = []
    if direction != "inbound":
        q_out = Message.query.filter(Message.company_id.is_(None))
        if status:
            q_out = q_out.filter(Message.status == status)
        if kind:
            q_out = q_out.join(Channel, Channel.id == Message.channel_id) \
                          .filter(Channel.kind == kind)
        if source_module:
            q_out = q_out.filter(Message.source_module == source_module)
        for m in q_out.order_by(Message.id.desc()).limit(limit).all():
            d = _message_dict(m)
            d["direction"] = "outbound"
            items.append(d)
    if direction != "outbound":
        q_in = InboundMessage.query.filter(InboundMessage.company_id.is_(None))
        for i in q_in.order_by(InboundMessage.id.desc()).limit(limit).all():
            d = _inbound_dict(i)
            d["direction"] = "inbound"
            # Унификация status/kind для inbound: всегда 'received', kind='telegram'.
            d["status"] = "received"
            d["kind"] = "telegram"
            items.append(d)
    # Сортируем по created_at DESC (строки — ISO, сравниваемы лексикографически).
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return jsonify({"items": items[:limit]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
