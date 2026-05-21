# CORPER Module — Служба рассылок

> **Важно для AI-ассистента и разработчика — прочитай этот раздел в первую очередь.**

## Где вы находитесь

Этот репозиторий — **отдельный модуль портала CORPER**. Вы (и ваш AI-агент) работаете
**на машине разработчика**, а не на сервере портала. Это две разные системы:

```
┌────────────────────────────┐         ┌──────────────────────────────────────┐
│ Машина разработчика        │  push   │ Сервер портала CORPER                │
│ (где вы читаете этот файл) │ ──────▶ │ http://10.101.10.181:5000             │
│                            │ GitHub  │                                       │
│ - git clone модуля         │         │ - Все core-сервисы (auth, registry,   │
│ - npm run dev              │ ◀────── │   redis, postgres, nginx)             │
│ - локальные правки кода    │   pull  │ - Все запущенные модули (контейнеры)  │
│ - vite proxy → 10.101...   │         │ - Deploy Agent (/admin/deploy)        │
│ - НЕТ доступа к контейнерам│         │ - GitHub OAuth + auto-deploy          │
│ - НЕТ доступа к БД портала │         │                                       │
└────────────────────────────┘         └──────────────────────────────────────┘
```

**Что это значит для AI-агента:**

| ❌ НЕ делать на dev-машине | ✅ Что делать на dev-машине |
|----------------------------|------------------------------|
| `docker compose` (главного портала, в `~/corper`) | `docker compose -f docker-compose.dev.yml up` (этот модуль) |
| `psql`, прямой доступ к БД портала | Локальный `db:` контейнер в dev-стеке + API портала |
| Перезапуск контейнеров портала | `git commit`, `git push` (deploy сделает портал) |
| Чтение `/etc/nginx/...` портала | Запросы к `/api/deploy/docs/public/...` для актуальной доки |
| `docker exec` в `corper-*-service` (на портале) | `docker compose -f docker-compose.dev.yml exec backend ...` (локально) |
| `alembic upgrade head` против БД портала | `alembic` в локальном backend-контейнере dev-стека |

**⚠ Multi-company:** один пользователь может быть в нескольких компаниях.
Активную компанию shell сообщает каждому API-запросу как `?company_id=N`.
Backend **обязан** читать company_id из запроса (хелпер `_active_company_id()`
в `backend/app.py`), а **не** из `current_user.company_id` — иначе записи одной
компании видны в другой. Подробности → раздел «Multi-company» ниже.

**Деплой всегда происходит на сервере портала**, не на вашей машине. Алгоритм:

```
ВЫ:  правки → git commit → git push origin main
     ↓
ПОРТАЛ: super_admin открывает /admin/deploy → находит коммит → Deploy
     ↓
DEPLOY-AGENT: pull → build → restart → nginx reload
```

Если у модуля есть `backend/` директория — на портале параллельно живут 2-3 контейнера
(`corper-module-mailer` + `corper-mailer-service` + опц. `pg-mailer`). См. `module.json` в корне.

---

## Параметры модуля

| Параметр | Значение |
|----------|----------|
| **Название** | Служба рассылок |
| **Секция прав** | `notifications` (`VITE_MODULE_SECTION`) |
| **Маршрут** | `mailer` (`VITE_MODULE_NAME`) |
| **URL портала (prod)** | `http://10.101.10.181:5000` |
| **URL портала (для dev `.env`)** | `VITE_PORTAL_URL=http://10.101.10.181:5000` |
| **Иконка** | `send` (Feather Icons) |
| **route_prefix** | `/mailer` |
| **remote_url** | `/remotes/mailer` |

`localhost:5000` в этом файле = «локальный портал на той же машине». Если вы клонировали репо
на свой ПК, **порт 5000 у вас на localhost не работает** — поставьте в `.env.development`
адрес реального портала: `VITE_PORTAL_URL=http://10.101.10.181:5000`.

---

## Быстрый старт (на машине разработчика)

**Запускайте модуль через Docker**, в той же структуре, что задана в `module.json`:
1 контейнер (frontend-only) или 2-3 (frontend + backend + опционально dedicated postgres).
Файл `docker-compose.dev.yml` уже сгенерирован под структуру вашего модуля.

```bash
# 0. Залогиньтесь в портале (один раз). Браузер сохранит cookie corper_token —
#    Vite proxy пробросит его на portal API.
#    Откройте http://10.101.10.181:5000/login

# 1. Поднять стек модуля локально
docker compose -f docker-compose.dev.yml up --build

# 2. Открыть http://localhost:5080 — frontend с hot-reload
#    (для модулей с backend он тоже стартует — слушает на :5000)
```

Состав dev-стека определяется автоматически по `module.json`:

| `components` в module.json | Что поднимется в dev |
|-----------------------------|----------------------|
| `frontend` | `frontend` (Vite dev server, hot-reload) |
| `frontend + backend` (без БД) | `frontend` + `backend` (gunicorn `--reload`) |
| `frontend + backend + dedicated DB` | `frontend` + `backend` + `db` (postgres + dev-init.sql) |

Если разработчик хочет работать только над frontend без локального backend —
можно поднять выборочно:

```bash
docker compose -f docker-compose.dev.yml up frontend
```

Тогда `/api/*` пойдёт через Vite proxy на портал (production backend), `/api/mailer/*` —
тоже на портал (production backend модуля). Локальный backend стартовать не обязательно.

### Управление dev-стеком

```bash
# Остановить
docker compose -f docker-compose.dev.yml down

# Сбросить локальную БД (volume)
docker compose -f docker-compose.dev.yml down -v

# Логи одного контейнера
docker compose -f docker-compose.dev.yml logs -f backend

# Перезайти в backend для отладки/alembic
docker compose -f docker-compose.dev.yml exec backend bash
```

### Альтернатива: голый node (если не хотите docker)

```bash
npm install
cp .env.example .env.development        # уже указывает VITE_PORTAL_URL=10.101.10.181:5000
npm run dev                              # → http://localhost:5080
```

Этот путь даёт только frontend. Backend всё равно придётся поднимать через docker
или тестировать против deployed backend на портале.

### Dev Toolbar — переключение контекста

В dev-режиме в правом нижнем углу есть иконка gear. По клику открывается плавающая панель **DevToolbar**:

- **Авторизация** — если нет cookie, можно залогиниться прямо из панели
- **Пользователь** — имя и роль текущего пользователя
- **Компания** — dropdown для переключения между доступными компаниями
- **Филиалы** — список филиалов активной компании
- **Сотрудники** — список сотрудников (до 20) с ролями и должностями
- **Права** — view/manage статус для секции модуля

При переключении компании все данные модуля автоматически перезагружаются. Состояние панели сохраняется между перезагрузками.

> DevToolbar **полностью отсутствует** в production-сборке — Vite удаляет его при `npm run build`. В iframe портала toolbar не появляется.

---

## Что вы получаете от портала

### usePortal() — composable

```ts
import { usePortal } from './composables/usePortal'

const { user, company, companies, branches, employees, companyId, loaded, load, canView, canManage, switchCompany } = usePortal()
onMounted(() => load())
```

| Поле | Тип | Описание |
|------|-----|----------|
| `user` | `PortalUser` | Текущий пользователь: id, name, role, permissions |
| `company` | `Company` | Активная компания: id, name, timezone |
| `companies` | `Company[]` | Все доступные компании (только dev) |
| `branches` | `Branch[]` | Филиалы компании |
| `employees` | `Employee[]` | Сотрудники компании (только dev) |
| `companyId` | `string` | ID активной компании |
| `loaded` | `boolean` | Данные загружены |
| `canView()` | `boolean` | Есть ли у пользователя доступ к модулю |
| `canManage()` | `boolean` | Может ли редактировать (add/edit/delete) |
| `switchCompany(id)` | `function` | Переключить компанию (dev) |
| `loadDepartment(deptId, includeEmployees?)` | `function` | Rich-срез по подразделению (`/full`) — manager, ancestors, descendants, subtree-сотрудники. См. INTEGRATION.md |

### API портала (межмодульные справочники)

| Endpoint | Описание |
|----------|----------|
| `GET /api/me` | Текущий пользователь + матрица прав |
| `GET /api/employees` | Сотрудники компании |
| `GET /api/employees/search` | Поиск: q, branch_id, department, limit |
| `POST /api/employees/resolve` | Batch-резолв по массиву ID |
| `GET /api/departments` | Отделы компании (distinct) |
| `GET /api/positions` | Должности компании (distinct) |
| `GET /companies/{id}` | Данные компании |
| `GET /companies/{id}/branches` | Филиалы |
| `GET /branches/{id}` | Один филиал по ID |
| `GET /api/branches/{id}/employees` | Сотрудники филиала |
| `GET /api/company/{id}/stats` | Счётчики: сотрудники, филиалы, отделы |
| `GET /employees/{id}/permissions` | Проверка прав (backend) |
| `GET /api/sections` | Все секции прав |
| `GET /api/module-registry` | Список модулей |
| `POST /mail/send` | Отправить уведомление (backend) |
| **`GET /api/companies/{cid}/departments/{did}/full`** | **Rich-срез:** dept + manager + ancestors + descendants + direct_reports + subtree-сотрудники. Один endpoint для любых модулей со структурой (mail, tasks, analytics). См. INTEGRATION.md |

Все SPA-запросы автоматически авторизованы через cookie `corper_token`.
Полный справочник: `/admin/deploy` → секция **API Reference** или `GET /schema` (OpenAPI 3.0).
Подробнее: см. `INTEGRATION.md`.

---

## Multi-company: как определить активную компанию

> **Самая частая ошибка модуля** — данные одной компании показывают всем.
> Прочтите этот раздел перед написанием любого CRUD.

Один пользователь может быть в нескольких компаниях и переключаться между ними
через dropdown в правом верхнем углу shell. **Backend модуля об этом переключении
напрямую не знает.** Shell сообщает выбранную компанию каждому запросу как
`?company_id=N` (плюс кладёт в `localStorage["activeCompanyId"]` для iframe).

### ❌ Что НЕ работает (приводит к утечке между компаниями)

```python
# ПЛОХО — current_user.company_id / active_company_id это ДЕФОЛТНАЯ компания
# пользователя из core-registry, а не та, что он выбрал в shell.
items = Item.query.filter_by(company_id=current_user.company_id).all()
items = Item.query.filter_by(company_id=current_user.active_company_id).all()
```

Оба поля возвращают одно и то же значение для всех запросов в течение сессии —
независимо от того, какую компанию пользователь сейчас смотрит. Поэтому
созданная в одной компании запись видна в другой (или, наоборот, никогда не видна).

### ✅ Правильный паттерн

Используйте helper из `corper-shared` — он есть в каждом scaffold-модуле:

```python
from corper_shared.context import active_company_id, require_section

@app.get("/items")
@login_required
def list_items():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    return jsonify([i.to_dict() for i in Item.query.filter_by(company_id=company_id)])
```

`active_company_id` сам читает `?company_id=` из запроса, валидирует доступ
(admin/super_admin — обход, остальные должны быть в `current_user.company_ids`),
и абортит 400/403 при проблемах. **Используйте его в каждом endpoint, который читает
или пишет company-scoped данные.** Никогда не доверяйте `current_user.company_id`
напрямую для фильтрации записей.

Если нужна привязка к филиалу — есть `assert_branch_access(user, company_id, branch_id, core)`.

### Frontend: axios клиент уже шлёт company_id автоматически

В сгенерированном `src/api.ts` axios-инстанс берёт `companyId` из usePortal и
дописывает к каждому запросу. Если вы делаете запрос напрямую через `fetch`,
не забудьте передать `?company_id=` руками — иначе backend получит null и упадёт
в 400.

---

## Система прав

> **Вы НЕ реализуете свою систему прав.**

Портал полностью управляет доступом к модулю:

- **Кто видит модуль** — решает админ портала через конструктор ролей
- **Shell проверяет права** перед загрузкой iframe (нет доступа = модуль не загрузится)
- **Вы используете `canView()` / `canManage()`** для UI-логики:
  - `canView() = false` -> "Доступ запрещен" (уже реализовано в Module.vue)
  - `canManage() = false` -> скрыть кнопки Добавить/Редактировать/Удалить
  - `canManage() = true` -> показать все action-кнопки

### Роли портала

| Роль | canView | canManage | Описание |
|------|---------|-----------|----------|
| `super_admin` | всегда `true` | всегда `true` | Полный доступ |
| `admin` | всегда `true` | всегда `true` | Полный доступ в компании |
| `manager/employee` | по permissions | по permissions | Настраивается админом |

---

## Структура проекта

```
module.json                  <- манифест деплоя (контракт с deploy-agent)
docker-compose.dev.yml       <- локальный dev-стек (frontend + опц. backend + db)
Dockerfile                   <- prod-сборка frontend (Vite build → nginx)
package.json, vite.config.ts <- frontend bootstrap (не трогать без причины)

src/                         <- Vue 3 SPA
  main.ts                    <- точка входа (не трогать)
  Module.vue                 <- корневой компонент (табы, проверка прав)
  config.ts                  <- конфигурация из ENV (не трогать)
  api.ts                     <- axios клиент с auto company_id
  types.ts                   <- типы данных портала + свои типы
  composables/
    usePortal.ts             <- доступ к данным портала (не трогать)
  components/
    DevToolbar.vue           <- dev-панель (не трогать, отсутствует в prod)
  pages/
    ExamplePage.vue          <- пример (замените своими страницами)

backend/                     <- (только если в module.json есть components.backend)
  app.py                     <- Flask routes, login_required, require_view/manage
  models.py                  <- SQLAlchemy модели
  requirements.txt
  Dockerfile                 <- prod-сборка backend (gunicorn)
  alembic.ini, alembic/      <- миграции БД
  dev-init.sql               <- (только если db_mode=dedicated) — schema в dev DB
  _corper-shared/            <- placeholder; реальный пакет inject'ится при деплое
                              или скачивается с портала в dev-сборке
```

### Что можно менять:
- `Module.vue` — добавляйте свои вкладки
- `pages/` — создавайте свои страницы
- `api.ts` — добавляйте свои endpoints
- `types.ts` — дополняйте своими типами
- `backend/app.py`, `backend/models.py` — ваш backend и схема БД
- `backend/alembic/versions/*.py` — миграции (создаются `alembic revision`)

### Что нельзя менять:
- `config.ts`, `composables/usePortal.ts` — контракт с порталом
- `module.json` без понимания последствий — это контракт деплоя; для смены БД/auth перевыпустите wizard'ом
- `backend/_corper-shared/.placeholder` — placeholder для COPY в Dockerfile

---

## Технологический стек

Модуль использует основной стек проекта. Отклонение допускается при обоснованной необходимости.

| Слой | Технология |
|------|------------|
| Frontend | Vue 3, TypeScript, Vite 6, Axios |
| Composable | usePortal() — доступ к данным портала |
| Backend (если нужен) | Python 3.11, Flask, SQLAlchemy, corper-shared |
| БД (если нужен) | PostgreSQL 16 |

### Миграции БД

Если у модуля есть свой backend с БД — **любое изменение схемы требует миграционного скрипта**.

```
1. Изменить models.py
2. Подготовить SQL-скрипт или Alembic revision
3. Скрипт должен быть идемпотентным (безопасно запускать повторно)
4. Включить скрипт в коммит вместе с изменением модели
```

`db.create_all()` НЕ обновляет существующую БД. На production изменения применяются только через миграции.

---

## Стилевые соглашения

| Параметр | Значение |
|----------|----------|
| Шрифт | Inter (подключен в index.html) |
| Primary | `#4338ca` (индиго) |
| Secondary | `#6366f1` |
| Текст | `#1a1a2e` (темный), `#8b8fa3` (серый) |
| Фон | `#f8f9fb` |
| Карточки | `background: #fff`, `border: 1px solid #f0f0f0`, `border-radius: 12px` |
| Кнопки | `border-radius: 8px`, `font-size: 13px` |
| Иконки | Feather Icons (глобально доступны через `feather.replace()`) |

---

## Актуальная документация

Документация обновляется централизованно. Актуальные версии всегда доступны:

- **Правила разработки**: `http://10.101.10.181:5000/api/deploy/docs/public/templates/README.md`
- **API-контракт**: `http://10.101.10.181:5000/api/deploy/docs/public/templates/INTEGRATION.md`
- **Деплой модуля**: `http://10.101.10.181:5000/api/deploy/docs/public/templates/DEPLOYMENT.md`
- **Архитектура портала**: `http://10.101.10.181:5000/api/deploy/docs/public/architecture/CLAUDE.md`
- **Все документы**: `http://10.101.10.181:5000/api/deploy/docs/public`

Для обновления документации в модуле попросите AI:
"Скачай актуальную документацию с http://10.101.10.181:5000/api/deploy/docs/public и обнови файлы модуля"
