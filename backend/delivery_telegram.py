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
                 parse_mode: str = "HTML") -> dict:
    """sendMessage → {message_id, chat, ...}"""
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                     "disable_web_page_preview": True}
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    return _request(bot_token, "sendMessage", **payload)


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
