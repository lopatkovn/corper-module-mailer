# INSTRUCTIONS — модуль «Служба рассылок» (corper-module-mailer)

> Рабочее руководство по реализации модуля. Полный roadmap — в plan-файле
> `/home/react/.claude/plans/nifty-sauteeing-seahorse.md`. README — общая инфраструктура
> портала; этот файл — что делать здесь и сейчас.

## 0. Что это за модуль

Централизованный **hub доставки служебных уведомлений** портала CORPER. Принимает события
от модулей-источников (audio, tasks, checklists, core, …) и доставляет их:
- по **email** (SMTP),
- в **Telegram-группы** (бот свой на каждую компанию).

Двусторонний: принимает ответы/команды из Telegram-групп (long polling).

Модуль размещён в разделе **«Организация»** портала (`/org/notifications`, секция прав
`notifications`). Деплоится через deploy-agent.

**Принцип**: модули-источники НЕ настраивают рассылку сами — они только публикуют события
(`POST /api/mailer/events`). Каналы, правила маршрутизации, получатели, Telegram-группы
настраиваются централизованно в этом модуле.

## 1. Quick start

```bash
git clone https://github.com/lopatkovn/corper-module-mailer.git
cd corper-module-mailer
cp .env.example .env
npm install
docker compose -f docker-compose.dev.yml up -d   # backend + postgres
npm run dev                                        # vite, http://localhost:5173
```

Дев-учётка портала: `admin@clockster.local` / `Admin1234` (super_admin).

## 2. Что уже есть в scaffold

deploy-agent сгенерировал full-stack scaffold: frontend (Vue), backend (Flask + alembic),
`module.json`, `docker-compose.dev.yml`, `backend/_corper-shared/` (placeholder).
**Worker-контейнера пока нет** — его добавляете вы (Фаза 2, см. §5).

Развёрнутые контейнеры на портале: `corper-module-mailer` (frontend),
`corper-mailer-service` (backend), `pg-mailer` (БД `corper_mailer`, schema `mailer`).

## 3. ⚠️ Pitfalls — проверить перед каждым коммитом

Грабли, на которые уже наступали в соседних модулях:

- [ ] **`make_request_loader` подключён** в `backend/app.py`. Без него все `@login_required`
  endpoints возвращают **401** даже при валидном токене. Минимальный auth-блок — см. §A.
- [ ] **`_active_company_id()` используется** во всех endpoints (не `current_user.company_id`) —
  иначе данные одной компании видны в другой.
- [ ] **alembic upgrade проходит чисто** — при raw SQL экранируйте `%` → `%%`.
- [ ] **route_prefix = `/org/notifications`** (не `/notifications`!). Модуль в разделе
  «Организация». Сейчас в `module_registry` уже стоит правильно (поправлено вручную). Если
  будете пересоздавать модуль — проверьте route_prefix снова, иначе пункт меню упрётся в Stub.
- [ ] **Токены (SMTP-пароль, Telegram bot token) — НЕ в `pg-mailer`**, а в `core.module_secret`.
  Не логировать, в API-ответах отдавать маскированными.
- [ ] **`./scripts/docker-status.sh mailer`** (на портале) — все контейнеры `running`.

### A. Минимальный auth-блок backend/app.py

```python
from corper_shared.auth import make_user_loader, make_request_loader, ProxyEmployee

login_manager = LoginManager(app)
login_manager.user_loader(make_user_loader(core))
if os.environ.get("DEV_AUTH_BYPASS") == "1":
    # dev-режим без портала — фиксированный пользователь
    ...  # см. corper-module-checklists/backend/app.py
else:
    login_manager.request_loader(make_request_loader(core, app.config["SECRET_KEY"]))
```

## 4. Архитектура и БД

### 4.1 БД `pg-mailer` (schema `mailer`) — 7 таблиц

Полный DDL — в plan-файле §2. Кратко:

| Таблица | Назначение |
|---|---|
| `channel` | каналы компании (email-SMTP / telegram-bot). `secret_ref` → ключ в `core.module_secret` |
| `telegram_group` | реестр ТГ-групп: chat_id, привязка к филиалу, статус бота (is_member, can_send) |
| `event_type` | каталог типов событий (сид ядра + sync из `module.json.emits` модулей) |
| `routing_rule` | правило «тип события → канал → получатели/группа» |
| `message` | очередь/журнал исходящих (email + telegram), статусы pending/sent/failed |
| `inbound_message` | входящие из Telegram (long polling), сопоставление reply → message |
| `poll_state` | курсор `getUpdates` (last_update_id) на каждого бота |

Все таблицы — с `company_id` (мультикомпанийность, 20 компаний).

### 4.2 API `/api/mailer/*`

**Inter-service** (вызывают модули-источники):
- `POST /events` — приём события `{company_id, source_module, event_type, payload, branch_id?, dedup_key?}`
- `GET /groups?company_id=N` — список ТГ-групп со статусом бота
- `GET /groups/{id}/status` — детальный статус
- `POST /event-types/sync` — upsert каталога (вызывает deploy-agent при деплое модулей)

**UI-CRUD**:
- `GET/PUT /channels/email` + `POST /channels/email/test`
- `GET/PUT /channels/telegram` + `POST /bot/check` (getMe)
- CRUD `/groups`, `/rules`
- `GET /event-types`, `/messages` (журнал), `/inbound`

### 4.3 Frontend `/org/notifications`

Вкладки: **Каналы** (SMTP + Telegram-бот) · **Группы** (реестр ТГ-групп) ·
**Правила** (event_type → канал → получатели) · **Журнал** (исходящие + входящие).

## 5. Worker (Фаза 2+)

Добавьте контейнер `mailer-worker` — в `module.json` секцию:
```json
"worker": { "context": "backend", "command": "python worker.py" }
```
deploy-agent поднимет 4-й контейнер. Worker — один процесс, три потока:

- **A — Outbox**: каждые 5с шлёт `message WHERE status=pending` (email через SMTP,
  Telegram через `sendMessage`). Также читает legacy `core.mail_queue` (мост, см. §6).
- **B — Telegram long polling**: `getUpdates?offset=&timeout=25` → `inbound_message`,
  курсор в `poll_state`. Распознаёт команды, `my_chat_member` (бот добавлен в группу), reply.
- **C — Health-check**: раз в 10 мин `getChatMember(bot)` → `is_member`/`can_send` групп.

Rate-limit: ≤25 msg/sec на бот, ≤20 msg/min в группу (token-bucket).

⚠️ **Webhook НЕ используем** — портал на внутреннем IP без публичного HTTPS. Только long polling.

## 6. Судьба notify-service

mailer-worker **заменяет** старый `notify-service` (Node.js). В Фазе 2 worker дополнительно
читает legacy `core.mail_queue` (письма активации/сброса пароля). В **том же релизе**,
где worker начинает читать `core.mail_queue`, контейнер `notify-service` удаляется из
`docker-compose.yml` — нельзя держать оба активными (двойная отправка).

## 7. План фаз

| Фаза | Содержание | Результат |
|---|---|---|
| **1** | Скелет: модели §4.1, миграции, CRUD-заглушки, `POST /events` (пишет в `message`), каркас UI | Раздел открывается, события в журнале `pending` |
| **2** | Email: UI SMTP + тест-письмо, worker поток A, чтение legacy `core.mail_queue`, удаление notify-service | Письма уходят через mailer |
| **3** | Telegram исходящий: UI бота + `getMe`, `sendMessage`, rate-limiter, реестр групп | Событие → ТГ-группа |
| **4** | Long polling: поток B, автопривязка групп (`my_chat_member`), команды `/start` `/status` | Бот добавлен в группу → она появилась сама |
| **5** | Health-check (поток C), shared `TelegramGroupSettings.vue`, интеграция audio/tasks/checklists | Модули шлют события |
| **6** | Двусторонние ответы (reply → модуль), `_queue_mail()` → `POST /events`, шаблоны | Ответ в ТГ → действие в модуле |

## 8. Каталог событий

Модули-источники объявляют события в своём `module.json`:
```json
"emits": [
  {"event_type":"tasks.task.overdue","label":"Задача просрочена"}
]
```
deploy-agent при деплое вызывает `POST /api/mailer/event-types/sync`. Каталог ядра
(`core.account.activation`, `core.employee.created`, `core.password.reset`) — сид миграцией.

## 9. Verification

```bash
# 1. Контейнеры
docker ps --filter name=mailer

# 2. Backend жив
curl -b "corper_token=$T" http://10.101.10.181:5000/api/mailer/channels/email

# 3. Приём события
curl -X POST -b "corper_token=$T" http://10.101.10.181:5000/api/mailer/events \
  -H 'Content-Type: application/json' \
  -d '{"company_id":1,"source_module":"tasks","event_type":"tasks.task.overdue","payload":{}}'

# 4. Журнал
docker exec pg-mailer psql -U mailer_user -d corper_mailer \
  -c "SELECT id, event_type, status FROM mailer.message;"

# 5. SMTP тест (Фаза 2)
curl -X POST -b "corper_token=$T" http://10.101.10.181:5000/api/mailer/channels/email/test \
  -d '{"to":"you@example.com"}'

# 6. Telegram (Фаза 3): getMe зелёный, бот в группе → группа в реестре
```

## 10. Размещение в портале — что нужно в core

Эти правки делаются в репо `corper-registry` / `corper-frontend` отдельным PR
(координируйтесь с владельцем core):

- [corper-registry/models.py](corper-registry/models.py) — добавить `("notifications","Служба рассылок")` в `SECTIONS`
- [corper-frontend/src/components/AppLayout.vue](corper-frontend/src/components/AppLayout.vue) — пункт меню в группе `org`:
  `{icon:'send', label:'Служба рассылок', url:'/org/notifications', section:'notifications'}`
- [corper-deploy-agent/registry_client.py](corper-deploy-agent/registry_client.py) — `_resolve_route_prefix`:
  для org-зоны (`notifications`, `directories`) отдавать `/org/{section}` — чтобы при будущих
  пересозданиях модуля route_prefix был правильным автоматически.

## 11. Ссылки

- Полный план: `/home/react/.claude/plans/nifty-sauteeing-seahorse.md`
- README — инфраструктура портала, мульти-компания, deploy-цикл
- INTEGRATION.md — контракты shell↔module
- Образец full-stack модуля: `corper-module-checklists`
- Портал: `http://10.101.10.181:5000` · Deploy Agent: `/admin/deploy`
- GitHub: `https://github.com/lopatkovn/corper-module-mailer`
