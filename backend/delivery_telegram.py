"""Telegram Bot API клиент для mailer worker.

Использует HTTP-методы Bot API напрямую через `requests`. Никаких внешних
зависимостей кроме requests.

Лимиты Telegram обеспечивает rate_limit.BotRateLimiter перед вызовом
send_message (worker thread A).
"""
import requests


TG_API = "https://api.telegram.org"


class TelegramError(Exception):
    """Любая ошибка Telegram API."""
    def __init__(self, message: str, *, status_code: int | None = None,
                 retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def _request(bot_token: str, method: str, **params) -> dict:
    """Один HTTP-запрос к Bot API. Бросает TelegramError при неудаче."""
    if not bot_token:
        raise TelegramError("bot_token не задан")
    url = f"{TG_API}/bot{bot_token}/{method}"
    try:
        r = requests.post(url, json=params, timeout=35)
    except requests.RequestException as e:
        raise TelegramError(f"HTTP {type(e).__name__}: {e}") from e
    try:
        data = r.json()
    except ValueError:
        raise TelegramError(f"non-JSON response: HTTP {r.status_code}", status_code=r.status_code)
    if r.status_code >= 400 or not data.get("ok"):
        desc = data.get("description") or f"HTTP {r.status_code}"
        retry_after = (data.get("parameters") or {}).get("retry_after")
        raise TelegramError(desc, status_code=r.status_code, retry_after=retry_after)
    return data.get("result") or {}


def get_me(bot_token: str) -> dict:
    """getMe → {id, username, first_name, ...}"""
    return _request(bot_token, "getMe")


def send_message(bot_token: str, chat_id: int | str, text: str,
                 reply_to_message_id: int | None = None,
                 message_thread_id: int | None = None,
                 reply_markup: dict | None = None,
                 parse_mode: str = "HTML") -> dict:
    """sendMessage → {message_id, chat, ...}

    `message_thread_id` — для форум-чатов: указывает в какой топик отправить.
    None — общее сообщение (без треда).
    `reply_markup` — keyboard / inline-keyboard / ForceReply / ReplyKeyboardRemove.
    Используется в TG-регистрации для request_contact keyboard'а.
    """
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                     "disable_web_page_preview": True}
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    if message_thread_id is not None:
        payload["message_thread_id"] = int(message_thread_id)
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _request(bot_token, "sendMessage", **payload)


# ── Bot-branding helpers ──────────────────────────────────────────────────
# https://core.telegram.org/bots/api#getmyname (и парные set*)

def get_my_name(bot_token: str, language_code: str = "") -> dict:
    """getMyName → {name: '...'}"""
    p: dict = {}
    if language_code: p["language_code"] = language_code
    return _request(bot_token, "getMyName", **p)


def get_my_description(bot_token: str, language_code: str = "") -> dict:
    """getMyDescription → {description: '...'}"""
    p: dict = {}
    if language_code: p["language_code"] = language_code
    return _request(bot_token, "getMyDescription", **p)


def get_my_short_description(bot_token: str, language_code: str = "") -> dict:
    """getMyShortDescription → {short_description: '...'}"""
    p: dict = {}
    if language_code: p["language_code"] = language_code
    return _request(bot_token, "getMyShortDescription", **p)


def get_my_commands(bot_token: str, scope_type: str = "default",
                    language_code: str = "") -> list[dict]:
    """getMyCommands → [{command,description}, ...]"""
    p: dict = {}
    if scope_type:
        p["scope"] = {"type": scope_type}
    if language_code:
        p["language_code"] = language_code
    res = _request(bot_token, "getMyCommands", **p)
    return res if isinstance(res, list) else []


def set_my_name(bot_token: str, name: str, language_code: str = "") -> dict:
    """setMyName(name<=64). Пустая строка очищает имя."""
    p: dict = {"name": name}
    if language_code: p["language_code"] = language_code
    return _request(bot_token, "setMyName", **p)


def set_my_description(bot_token: str, description: str,
                       language_code: str = "") -> dict:
    """setMyDescription(<=512). Пустая строка очищает."""
    p: dict = {"description": description}
    if language_code: p["language_code"] = language_code
    return _request(bot_token, "setMyDescription", **p)


def set_my_short_description(bot_token: str, short_description: str,
                             language_code: str = "") -> dict:
    """setMyShortDescription(<=120)."""
    p: dict = {"short_description": short_description}
    if language_code: p["language_code"] = language_code
    return _request(bot_token, "setMyShortDescription", **p)


def set_my_commands(bot_token: str, commands: list[dict],
                    scope_type: str = "default",
                    language_code: str = "") -> dict:
    """setMyCommands(commands=[{command, description}, ...]).
    Пустой список очищает (фактически deleteMyCommands)."""
    p: dict = {"commands": commands}
    if scope_type:
        p["scope"] = {"type": scope_type}
    if language_code:
        p["language_code"] = language_code
    return _request(bot_token, "setMyCommands", **p)


def get_chat_member(bot_token: str, chat_id: int | str, user_id: int) -> dict:
    """getChatMember → {status: 'creator'|'administrator'|'member'|'left'|'kicked', ...}"""
    return _request(bot_token, "getChatMember", chat_id=chat_id, user_id=user_id)


def get_updates(bot_token: str, offset: int = 0, timeout: int = 25,
                allowed_updates: list[str] | None = None) -> list[dict]:
    """getUpdates → список update'ов. Долгий polling: timeout до 25с.

    HTTP-таймаут даём чуть больше polling-таймаута, иначе getUpdates вернёт
    пустой ответ ровно когда наш HTTP уже стрельнул.
    """
    if not bot_token:
        raise TelegramError("bot_token не задан")
    url = f"{TG_API}/bot{bot_token}/getUpdates"
    payload = {"offset": offset, "timeout": timeout}
    if allowed_updates is not None:
        payload["allowed_updates"] = allowed_updates
    try:
        r = requests.post(url, json=payload, timeout=timeout + 10)
    except requests.RequestException as e:
        raise TelegramError(f"HTTP {type(e).__name__}: {e}") from e
    try:
        data = r.json()
    except ValueError:
        raise TelegramError(f"non-JSON response: HTTP {r.status_code}", status_code=r.status_code)
    if r.status_code >= 400 or not data.get("ok"):
        desc = data.get("description") or f"HTTP {r.status_code}"
        raise TelegramError(desc, status_code=r.status_code)
    return data.get("result") or []
