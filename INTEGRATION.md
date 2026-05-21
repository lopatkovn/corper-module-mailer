# API-контракт портала CORPER

> **AI-агент:** этот документ описывает API портала. Сами endpoints живут на
> **сервере портала** `http://10.101.10.181:5000`, а не на машине разработчика.
> В коде модуля используйте относительные пути (`/api/me`, `/employees`) — Vite proxy
> в dev'е и iframe (same-origin) в prod автоматически направят запрос на портал.

Все endpoints доступны по URL из `VITE_PORTAL_URL` (по умолчанию `http://10.101.10.181:5000`).
Авторизация: cookie `corper_token` (автоматически при `credentials: 'include'`).
Cookie выставляется при логине на `http://10.101.10.181:5000/login` — сначала залогиньтесь
на портале, потом перезагрузите dev-сервер модуля.

---

## Common API for modules

Сводка endpoint'ов, которые модуль будет использовать чаще всего. Все защищены
`@login_required`, валидируют принадлежность пользователя к компании (`?company_id=N`),
admin/super_admin получают доступ ко всем компаниям.

### Self-context — `/api/me/*`

| Endpoint | Что возвращает |
|----------|----------------|
| `GET /api/me` | id, name, portal_role, active company_id, company_ids, permissions, has_deploy_access |
| `GET /api/me/companies` | компании, в которых я состою, c моей `company_role` в каждой |
| `GET /api/me/branches?company_id=N` | мои филиалы в компании N (admin → все) |
| `GET /api/me/roles?company_id=N` | назначенные роли |
| `GET /api/me/groups?company_id=N` | мои группы (узлы dept с is_access_group=TRUE, в которых я состою через subtree) |
| `GET /api/me/permissions?company_id=N` | `{section: {can_view, can_manage, can_deploy}}` (admin → `null`) |
| `POST /api/me/permissions/check` | body `{company_id, section}` — on-demand проверка |

### Контекст компании — `/api/companies/{cid}/*`

| Endpoint | Что возвращает / делает |
|----------|--------------------------|
| `GET /api/companies/{cid}` | основная инфа: name, slug, timezone, logo, contacts |
| `GET /api/companies/{cid}/branches` | филиалы (для не-admin — пересечение с `employee_branch`) |
| `POST/PUT/DELETE /api/companies/{cid}/branches[/{bid}]` | CRUD филиалов (section `structure` manage) |
| `GET /api/companies/{cid}/employees` | сотрудники |
| `GET /api/companies/{cid}/employees/search?q=&branch_id=&department=&group_id=&limit=` | поиск с фильтрами |
| `GET /api/companies/{cid}/departments` | flat список (parent_id, manager, employee_count, descendants_count) |
| `GET /api/companies/{cid}/departments/tree` | nested tree |
| `GET /api/companies/{cid}/departments/matrix` | matrix-row (для табличного view) |
| `GET /api/companies/{cid}/departments/{did}` | подробности: dept + manager + direct_reports + subdepartments |
| `POST/PUT/DELETE /api/companies/{cid}/departments[/{did}]` | CRUD (section `structure`) |
| `GET /api/companies/{cid}/departments/{did}/employees?include_descendants=1` | сотрудники узла (+ опц. поддерево) |
| **`GET /api/companies/{cid}/departments/{did}/full`** | **rich-эндпоинт**: dept + manager + ancestors + descendants + direct_reports + subtree counts. Опц. `?include_subtree_employees=1`, `?descendants_depth=N` |
| `POST /api/companies/{cid}/departments/{did}/employees` | назначить в отдел (body `{employee_ids: [...]}`, silent-skip кросс-компани; section `structure`) |
| `DELETE /api/companies/{cid}/departments/{did}/employees/{eid}` | убрать из отдела (`department_id=NULL`); section `structure` |

#### Rich endpoint `/full` — единый источник по подразделению

Возвращает всё, что обычно нужно модулю о конкретном узле:

```json
{
  "id": 5, "company_id": 1, "parent_id": 1,
  "name": "HR", "description": "...", "color": null, "sort_order": 0,
  "manager_id": 9,
  "manager": { "id": 9, "name": "...", "position": "...",
               "avatar_color": "...", "initials": "АИ" },
  "is_branch": false, "is_access_group": false, "is_mailing_list": true,
  "mail_alias": "hr@company.local",
  "address": null, "phone": null, "lat": null, "lng": null,
  "ancestors": [ { "id": 1, "name": "Koreana Light" } ],
  "direct_reports": [ { "id": 3, "name": "...", "position": "...",
                        "email": "...", "phone": "...",
                        "avatar_color": "...", "initials": "...",
                        "department_id": 5 } ],
  "direct_reports_count": 3,
  "descendants": [
    { "id": 12, "parent_id": 5, "name": "Recruiting",
      "manager": { ... }, "is_branch": false, "is_access_group": false,
      "is_mailing_list": false, "depth": 1, "direct_employee_count": 4 }
  ],
  "descendants_count": 1,
  "subtree_employee_count": 9,
  "subtree_employees": [ /* только при ?include_subtree_employees=1 */ ]
}
```

**Параметры:**
- `?include_subtree_employees=1` — добавить полный список сотрудников всего поддерева
- `?descendants_depth=N` — ограничить глубину выгружаемых потомков

**Use cases:**

```ts
// Mail: рассылка по отделу
const r = await axios.get(`/api/companies/${cid}/departments/${did}/full`,
                          { params: { include_subtree_employees: 1 } })
const emails = r.data.subtree_employees.map(e => e.email).filter(Boolean)
sendMail({ to: emails, subject: `[${r.data.mail_alias}] ...` })

// Tasks: назначить задачу руководителю отдела + всем подчинённым
const { manager, subtree_employees } = (await axios.get(
  `/api/companies/${cid}/departments/${did}/full?include_subtree_employees=1`
)).data

// Analytics: агрегаты по поддереву
const { descendants, subtree_employee_count } = (await axios.get(
  `/api/companies/${cid}/departments/${did}/full`
)).data
const byBranch = descendants.filter(d => d.is_branch)
```

**Bаckend (через CoreClient):**

```python
info = core.get_department_full(company_id, dept_id, include_subtree_employees=True)
```

Pull-only, всегда актуальные данные — это публичный контракт для любого модуля,
которому нужна иерархия + контакты вокруг узла.
| `GET /api/companies/{cid}/groups` | узлы с `is_access_group=TRUE` (это и есть "группы") |
| `GET /api/companies/{cid}/mailings` | узлы с `is_mailing_list=TRUE` |
| `GET /api/companies/{cid}/directories` | список справочников компании |
| `GET /api/companies/{cid}/directories/{key}` | items в справочнике |
| `POST/PUT/DELETE /api/companies/{cid}/directories[/{key}]` | CRUD (section `directories`) |
| `POST/PUT/DELETE /api/companies/{cid}/directories/{key}/items[/{iid}]` | CRUD items |
| `GET /api/companies/{cid}/roles` | read-only список ролей (полный CRUD — `/api/roles/*` admin only) |
| `GET /api/companies/{cid}/stats` | counts |

### Группы — `/api/groups/{gid}/*`

| Endpoint | Что |
|----------|-----|
| `GET /api/groups/{gid}/members` | сотрудники в этой группе (= subtree узла) |

### Глобальные справочники

| Endpoint | Что |
|----------|-----|
| `GET /api/sections` | все секции прав (key, label) |
| `GET /api/module-sections` | MODULE_SECTIONS — какие секции в каком модуле |
| `GET /api/module-registry` | активные модули портала |
| `POST /api/employees/resolve` | batch lookup `{ids: [...]}` (до 200) |

### Backend (inter-service)

Эти зовутся **из backend модуля** через `CoreClient`. На фронте не нужны.

| Endpoint | CoreClient метод |
|----------|------------------|
| `GET /employees/{id}` | `core.get_employee(id)` |
| `GET /employees/{id}/permissions?company_id=&section=` | `core.get_permissions(id, cid, section)` |
| `GET /companies/{id}` | `core.get_company(id)` |
| `GET /companies/{id}/branches` | `core.get_branches(cid)` |
| `GET /branches/{id}` | `core.get_branch(id)` |
| `GET /branches/{id}/employees` | `core.get_branch_employees(bid)` |
| `POST /mail/send` | `core.send_mail(to_employee_id, subject, body)` |

### Multi-company защита (важно!)

Backend модуля **должен** использовать helper `corper_shared.context.active_company_id`,
который читает company_id из запроса и валидирует доступ. См. раздел Multi-company в README.

### Архивные филиалы/группы/рассылки/узлы — soft-preserve policy

В CORPER **ничего из `org` не удаляется навсегда**. Две независимые оси архива:

- **Роль** (флаг на узле — филиал, группа, рассылка) → `*_archived_at` маркер
  на соответствующей строке. Узел остаётся активным.
- **Контейнер** (сам узел department) → `department.archived_at`. Каскадно
  переводит ВСЕ роли поддерева в архив. Триггерится «📦 Архивировать
  подразделение» из Структуры.

Если ваш модуль сохранил `branch_id` / `group_id` / `dept_id` / mailing-id, GET
по этому id **продолжит возвращать 200** с полем `"is_archived": true`
(+ `"archived_at"`). В списках по умолчанию архив скрыт; нужен явный
`?include_archived=1`.

Что должен делать модуль:

- **Резолв по id** — продолжает работать; вместо «404 → данные потерялись»
  получаете 200 с архивным флагом. Покажите бейдж «📦 Архив», заморозьте
  edit/write-операции.
- **При просмотре списков** — не запрашивайте `?include_archived=1` по
  умолчанию; включайте только если у пользователя есть фильтр «архив».
- **При создании/назначении новых ACL** — не выбирайте архивные сущности.

Пример (frontend, Vue 3):

```ts
const { data: branch } = await axios.get(`/api/companies/${cid}/branches/${bid}`)
if (branch.is_archived) {
  // show grey banner; gate write actions
  showBanner(`Филиал «${branch.name}» в архиве с ${branch.archived_at}`)
}
```

Пример (backend, через CoreClient):

```python
b = core.get_branch(branch_id)
if b.get("is_archived"):
    # freeze attached resources, keep them readable
    record["status"] = "archived_target"
```

Реактивация — повторное включение флага в Структуре (или для custom-групп —
`POST /api/companies/{cid}/groups/custom/{gid}/restore`).

---

---

## GET /api/me — Текущий пользователь

```json
{
  "id": 10,
  "name": "Иван Иванов",
  "email": "ivan@company.com",
  "portal_role": "employee",
  "is_active": true,
  "company_id": 1,
  "active_company_id": 1,
  "company_ids": [1, 2],
  "permissions": {
    "notifications": { "view": true, "manage": true, "deploy": false },
    "employees": { "view": true, "manage": false, "deploy": false }
  },
  "quick_menu": ["chat", "tasks"],
  "has_deploy_access": false
}
```

`permissions` — матрица прав для **активной** компании. Ключ = section name.
`portal_role`: `super_admin | admin | manager | employee`
`admin/super_admin` — `permissions = null` (доступ ко всему).
`has_deploy_access` — `true` если super_admin или есть хотя бы 1 модуль в deploy_access.

---

## GET /companies/{id} — Компания

```json
{
  "id": 1,
  "name": "Koreana Light",
  "slug": "koreanalight",
  "timezone": "Europe/Moscow",
  "phone": "+7 700 123 45 67",
  "email": "info@koreana.kz",
  "website": "https://koreana.kz",
  "legal_address": "ул. Примерная, 1",
  "owner_id": 1,
  "owner_name": "Администратор"
}
```

---

## GET /companies/{id}/branches — Филиалы

```json
[
  {
    "id": 1,
    "name": "Центральный офис",
    "address": "Алматы, ул. Абая 10",
    "phone": "+7 727 123 45 67",
    "lat": 43.238,
    "lng": 76.945
  }
]
```

---

## GET /api/employees?company_id={id} — Сотрудники

```json
[
  {
    "id": 10,
    "name": "Иван Иванов",
    "email": "ivan@company.com",
    "portal_role": "employee",
    "department": "HR",
    "position": "Менеджер",
    "phone": "+7 700 111 22 33",
    "is_active": true,
    "branch_names": "Центральный офис",
    "branch_ids": [1],
    "company_ids": [1]
  }
]
```

---

## GET /employees/{id}/permissions?company_id={cid}&section={section}

Для backend-сервисов: проверка прав конкретного пользователя.

```json
{
  "can_view": true,
  "can_manage": false,
  "can_deploy": false
}
```

`admin/super_admin` всегда возвращает `{ "can_view": true, "can_manage": true, "can_deploy": true/false }`.

---

## GET /branches/{id} — Филиал

```json
{
  "id": 1,
  "name": "Центральный офис",
  "address": "Алматы, ул. Абая 10",
  "phone": "+7 727 123 45 67",
  "lat": 43.238,
  "lng": 76.945,
  "company_id": 1
}
```

---

## GET /api/employees/search — Поиск сотрудников

Параметры: `q` (имя), `branch_id`, `department`, `active` (0/1), `limit` (макс 100).

```
GET /api/employees/search?q=Иван&branch_id=1&department=HR&limit=20
```

```json
[
  {
    "id": 10,
    "name": "Иван Иванов",
    "initials": "ИИ",
    "avatar_color": "linear-gradient(135deg, #667eea, #764ba2)",
    "position": "Менеджер",
    "department": "HR",
    "is_active": true
  }
]
```

---

## POST /api/employees/resolve — Batch-резолв

Принимает массив ID (макс 200), возвращает минимальные данные для аватаров и списков.

```json
// Request
{ "ids": [1, 5, 12, 34] }

// Response
[
  { "id": 1, "name": "Админ", "initials": "АД", "avatar_color": "...", "position": "CTO", "department": "IT", "is_active": true },
  { "id": 5, "name": "Мария", "initials": "МА", "avatar_color": "...", "position": "HR", "department": "HR", "is_active": true }
]
```

---

## GET /api/departments — Отделы компании

Уникальные названия отделов активной компании (только активные сотрудники).

```json
["HR", "IT", "Кухня", "Зал", "Бухгалтерия"]
```

---

## GET /api/positions — Должности компании

```json
["Менеджер", "Повар", "Администратор", "Бухгалтер"]
```

---

## GET /api/branches/{id}/employees — Сотрудники филиала (SPA)

Активные сотрудники филиала с данными для отображения.

```json
[
  {
    "id": 10, "name": "Иван Иванов", "initials": "ИИ",
    "avatar_color": "...", "position": "Менеджер",
    "department": "HR", "email": "ivan@company.com"
  }
]
```

---

## GET /api/company/{id}/stats — Статистика компании

```json
{
  "employee_count": 45,
  "employee_total": 52,
  "branch_count": 3,
  "department_count": 6,
  "departments": ["HR", "IT", "Кухня", "Зал", "Бухгалтерия", "Склад"]
}
```

---

## POST /mail/send — Отправить уведомление (inter-service)

Для backend-сервисов: кладёт email в очередь. Можно указать `to_employee_id` (email будет резолвлен) или `to_email`.

```python
core.send_mail(to_employee_id=10, subject="Новая задача", body="Вам назначена задача #42")
```

```json
// Request
{ "to_employee_id": 10, "subject": "Новая задача", "body": "..." }

// Response
{ "ok": true, "mail_id": 123 }
```

---

## Смена компании (iframe-интеграция)

Когда пользователь переключает компанию в портале, shell отправляет:

```js
// Parent -> iframe
window.postMessage({ type: 'company-changed', companyId: 2 }, '*')
```

Модуль слушает это событие в `usePortal()` и автоматически перезагружает данные.

Текущая компания также доступна через:
```js
localStorage.getItem('activeCompanyId')  // "1"
```

---

## Тема оформления (theme sync)

Shell применяет одну из 6 готовых палитр (`linen` / `snow` / `mist` / `sage` / `indigo` / `coral`) либо `custom` (3 корпоративных цвета компании, остальное derives). Модули обязаны выглядеть в той же палитре что и shell — без своих хардкоднутых цветов.

### Как это работает

1. **Shared themes.css** — shell отдаёт единый файл с CSS-переменными по адресу `/portal-shared/themes.css`. Модуль подключает его в `index.html`:
   ```html
   <html lang="ru" data-theme="linen">
     <head>
       <link rel="stylesheet" href="/portal-shared/themes.css">
       …
   ```

2. **Initial theme** — на mount iframe RemoteModule.vue пушит текущую тему через postMessage. Параллельно `usePortal()` сам читает `localStorage.getItem('app_theme:<companyId>')` как fallback (актуально для standalone-режима до прихода shell'овского события).

3. **Live updates** — при смене темы в shell:
   ```js
   // Parent -> iframe
   window.postMessage({
     type: 'theme-changed',
     themeId: 'indigo',                  // или 'custom'
     customColors: { accent, bg, surface },  // только для themeId === 'custom'
     customVars: { '--bg': '...', '--accent': '...', ... }  // готовый snapshot, только для 'custom'
   }, '*')
   ```
   `usePortal()` ловит и применяет: `data-theme` → `<html>`, custom-vars → `<style id="corper-custom-theme">`.

4. **Cross-tab sync** — `storage` event автоматически срабатывает при изменении localStorage в другой вкладке. `usePortal()` слушает и для этого.

### Что должен делать модуль

- Использовать **только design tokens** — `var(--accent)`, `var(--bg)`, `var(--surface)`, `var(--text)`, `var(--text-2)`, `var(--border)`, `var(--ring)` и т.д. Никаких `#4338ca`/`#1a1a2e` хардкодов.
- Шрифты: **Inter** для всего, **JetBrains Mono** для счётчиков (`12 чел.`) и eyebrow-labels (`КОМПАНИЯ`).
- Радиусы: 8–12px для карточек, 9px для кнопок, 5px для chip'ов.
- Не вводить свои тени тяжелее `0 6px 24px -8px rgba(0,0,0,.18)`.

### Список CSS-переменных

Минимальный набор, который модуль может использовать:

| Переменная | Назначение |
|---|---|
| `--bg` | Фон страницы |
| `--surface` | Фон карточек, drawer'ов, surface-кнопок |
| `--panel` | Фон вложенных секций, group-headers |
| `--border`, `--border-2`, `--border-strong` | Рамки разной интенсивности |
| `--text`, `--text-2`, `--text-3`, `--text-4` | Текст от основного к убывающему контрасту |
| `--placeholder` | Текст-плейсхолдеры |
| `--accent`, `--on-accent` | Акцентный цвет + контрастный текст на нём |
| `--accent-dim`, `--accent-muted` | Тёмная и приглушённая вариации accent |
| `--ring`, `--ring-strong` | Полупрозрачное свечение/обводки (для focus, hover) |
| `--hover-bg` | Фон при hover |
| `--status-active-bg`, `--status-active-fg` | Зелёный «активный» badge |
| `--role-bg`, `--role-fg` | Розовый «роль» badge |
| `--danger` | Деструктивные действия |
| `--kbd-bg` | Фон keyboard-chip'а (⌘K) |
| `--scrollbar` | Цвет ползунка scrollbar'а |

### Готовые UI-компоненты в шаблоне

Шаблон `corper-module-template/src/components/` содержит:
- `PageHeader.vue` — title + count + tabs + search + primary CTA slot (mirror shell)
- `Card.vue` — surface-карточка с eyebrow + title + body + action-slot
- `Btn.vue` — `<Btn variant="primary|ghost" icon="plus" danger>` универсальная кнопка
- `DevToolbar.vue` — dev-only switcher компании/сотрудника

Пример сборки страницы — см. `src/pages/ExamplePage.vue`.

---

## Коды ошибок

| HTTP | Значение |
|------|----------|
| 200 | OK |
| 401 | Не авторизован (нет/истек токен) |
| 403 | Нет прав (permissions) |
| 404 | Не найдено |

---

## Полный справочник API

Интерактивный справочник всех межмодульных эндпоинтов с описаниями, параметрами и схемами ответов:

- **Deploy Manager → API Reference**: `/admin/deploy` (секция внизу страницы)
- **OpenAPI 3.0 JSON**: `GET /schema` (машиночитаемый формат)

Справочник генерируется автоматически из кода core-registry и всегда актуален.

---

## Актуальная документация

Актуальная версия этого контракта: `http://10.101.10.181:5000/api/deploy/docs/public/templates/INTEGRATION.md`
