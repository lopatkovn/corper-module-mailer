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


from models import Channel, TelegramGroup, EventType, RoutingRule, Message, InboundMessage, PollState  # noqa: E402, F401


# ── helpers ────────────────────────────────────────────────────────────────

# Поля канала, которые модули-источники могут читать без прав на секцию
# `notifications`. Никаких credentials (host/port/token/password) — только
# флаг готовности и метаданные последнего теста.
_PUBLIC_CHANNEL_KINDS = ("email", "telegram")


def _channel_status(c: "Channel | None") -> str:
    """Сводный статус канала для inter-service потребителей."""
    if c is None or not c.is_enabled:
        return "unconfigured"
    if c.last_test_ok is True:
        return "ok"
    if c.last_test_ok is False:
        return "error"
    return "untested"  # включён, но тест ещё не прогоняли


def _channel_public(c: "Channel | None", kind: str) -> dict:
    """Inter-service view канала: без секретов. None → пустая заглушка."""
    if c is None:
        return {
            "kind": kind,
            "is_enabled": False,
            "label": "",
            "status": "unconfigured",
            "last_test_at": None,
        }
    return {
        "kind": c.kind,
        "is_enabled": bool(c.is_enabled),
        "label": c.label or "",
        "status": _channel_status(c),
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
    }


def _mask_email_config(cfg: dict) -> dict:
    """Admin GET — отдаём весь конфиг кроме пароля; password→bool флаг."""
    safe = dict(cfg or {})
    has_pwd = bool(safe.pop("password", None))
    safe["has_password"] = has_pwd
    return safe


def _mask_telegram_config(cfg: dict) -> dict:
    """Admin GET — отдаём метаданные бота кроме токена; bot_token→bool флаг."""
    safe = dict(cfg or {})
    has_token = bool(safe.pop("bot_token", None))
    safe["has_bot_token"] = has_token
    return safe


def _get_or_create_channel(company_id: int, kind: str) -> "Channel":
    c = Channel.query.filter_by(company_id=company_id, kind=kind).first()
    if c is None:
        c = Channel(company_id=company_id, kind=kind, is_enabled=False, config={})
        db.session.add(c)
        db.session.flush()
    return c


# ── routes ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "module": MODULE_NAME}


@app.get("/channels")
@login_required
def list_channels():
    """Inter-service: «какие каналы есть у компании и в каком они состоянии».

    Возвращает все известные виды каналов (email, telegram) — даже если
    запись в БД отсутствует (kind:..., is_enabled:false, status:'unconfigured').
    Никаких секретов в ответе нет — поэтому доступно любому залогиненному
    члену компании; модули-источники зовут это, чтобы решить «можно ли
    предложить пользователю этот способ».
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
        return jsonify({
            "kind": "email",
            "is_enabled": False,
            "label": "",
            "config": {"has_password": False},
            "last_test_at": None, "last_test_ok": None, "last_test_error": None,
        })
    return jsonify({
        "kind": c.kind,
        "is_enabled": c.is_enabled,
        "label": c.label or "",
        "config": _mask_email_config(c.config or {}),
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        "last_test_ok": c.last_test_ok,
        "last_test_error": c.last_test_error,
    })


@app.put("/channels/email")
@login_required
def put_email_channel():
    """Сохранить SMTP-настройки. Если в payload не пришёл `password` —
    оставляем уже сохранённый (чтобы UI мог не пере-ввод по каждому save)."""
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    cfg_in = dict(data.get("config") or {})

    c = _get_or_create_channel(company_id, "email")
    if "is_enabled" in data:
        c.is_enabled = bool(data["is_enabled"])
    if "label" in data:
        c.label = str(data.get("label") or "")[:120]

    # Merge config: новые поля поверх, password — только если явно прислан и непуст
    merged = dict(c.config or {})
    for k in ("host", "port", "use_tls", "username", "sender_name", "sender_email"):
        if k in cfg_in:
            merged[k] = cfg_in[k]
    if "password" in cfg_in:
        pwd = cfg_in.get("password")
        if pwd:  # пустую строку игнорируем — это «не менять»
            merged["password"] = pwd
    c.config = merged
    # Сбрасываем результат прошлого теста — настройки изменились
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
        return jsonify({
            "kind": "telegram",
            "is_enabled": False,
            "label": "",
            "config": {"has_bot_token": False},
            "last_test_at": None, "last_test_ok": None, "last_test_error": None,
        })
    return jsonify({
        "kind": c.kind,
        "is_enabled": c.is_enabled,
        "label": c.label or "",
        "config": _mask_telegram_config(c.config or {}),
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        "last_test_ok": c.last_test_ok,
        "last_test_error": c.last_test_error,
    })


@app.put("/channels/telegram")
@login_required
def put_telegram_channel():
    """Сохранить настройки Telegram-бота. bot_token — только если явно передан."""
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
