"""Token-bucket rate limiter — потокобезопасный.

Telegram Bot API лимиты:
  • 30 сообщений/сек глобально на бота — берём 25 с запасом
  • 20 сообщений/мин в одну группу/канал — берём ровно 20

Используется в worker.thread_a при отправке Telegram-сообщений: если бакет
пуст — оставляем message в pending, обработаем в следующем цикле.
"""
import threading
import time


class TokenBucket:
    """Простой token-bucket: capacity токенов, refill_rate в секунду."""

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def try_acquire(self, n: float = 1.0) -> bool:
        """Списать n токенов, если есть. Возвращает True если списали."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last = now
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False


class BotRateLimiter:
    """Двухуровневый лимитер: бакет на бота + бакет на каждый чат."""

    BOT_CAPACITY = 25.0          # tokens
    BOT_REFILL   = 25.0          # tokens/sec
    CHAT_CAPACITY = 20.0         # tokens
    CHAT_REFILL  = 20.0 / 60.0   # 20 в минуту

    def __init__(self):
        self._bots: dict[int, TokenBucket] = {}      # channel_id → bucket
        self._chats: dict[int, TokenBucket] = {}     # chat_id → bucket
        self._lock = threading.Lock()

    def _bucket_for_bot(self, channel_id: int) -> TokenBucket:
        with self._lock:
            b = self._bots.get(channel_id)
            if b is None:
                b = TokenBucket(self.BOT_CAPACITY, self.BOT_REFILL)
                self._bots[channel_id] = b
            return b

    def _bucket_for_chat(self, chat_id: int) -> TokenBucket:
        with self._lock:
            b = self._chats.get(chat_id)
            if b is None:
                b = TokenBucket(self.CHAT_CAPACITY, self.CHAT_REFILL)
                self._chats[chat_id] = b
            return b

    def try_send(self, channel_id: int, chat_id: int) -> bool:
        """Атомарно списать токен с бота и с чата. Если хоть один пуст — False."""
        bot_b = self._bucket_for_bot(channel_id)
        chat_b = self._bucket_for_chat(chat_id)
        # Берём оба токена; если второй не получили — возвращаем первый обратно
        if not bot_b.try_acquire():
            return False
        if not chat_b.try_acquire():
            # вернуть бот-токен
            with bot_b._lock:
                bot_b._tokens = min(bot_b.capacity, bot_b._tokens + 1)
            return False
        return True
