# Деплой модуля "Служба рассылок"

> **AI-агент / разработчик:** этот документ описывает, как изменения из этого
> репозитория попадают на портал. **Сам деплой запускается НЕ с вашей машины**,
> а на сервере портала через Deploy Agent.

---

## Архитектура деплоя

```
┌──────────────────────────┐    git push   ┌────────────────────┐
│ Машина разработчика      │ ─────────────▶│ GitHub             │
│ (вы здесь)               │               │ corper-module-mailer    │
└──────────────────────────┘               └─────────┬──────────┘
                                                     │ pull при Deploy
                                                     ▼
                              ┌──────────────────────────────────────┐
                              │ Сервер портала http://10.101.10.181:5000 │
                              │                                      │
                              │  Deploy Agent (/admin/deploy)        │
                              │  ├─ git pull                         │
                              │  ├─ docker build                     │
                              │  ├─ docker run                       │
                              │  ├─ alembic upgrade head (если есть) │
                              │  └─ nginx reload                     │
                              └──────────────────────────────────────┘
```

**Запомните:** вы НЕ запускаете `docker` или `alembic` локально для прод-деплоя.
Всё это делает Deploy Agent на сервере портала.

### Bundled modules

Некоторые модули **не** деплоятся через wizard — они встроены в core-registry +
shell (страницы в corper-frontend), и обновляются пересборкой core-сервисов:

- `org/structure` — иерархия отделов (с флагами branch/group/mailing)
- `org/branches` — справочник филиалов (auto-managed через Structure)
- `org/roles` — конструктор ролей
- `org/directories` — справочники
- `org/groups` (= `org/structure` с флагом is_access_group)
- `org/settings` — настройки компании

Если у вас «модуль» с одним из этих имён — он живёт в monorepo (core-registry +
corper-frontend), а не отдельным репо. Обновление: правьте код в monorepo →
push → Deploy Agent: Core Services → core-registry (или frontend) → Build & Deploy.

---

## Что уже выполнено (при создании модуля)

Deploy Agent при `init` через wizard:

- Создал GitHub-репозиторий `corper-module-mailer` (под вашим аккаунтом / org)
- Сгенерировал scaffold и запушил начальный коммит
- Записал модуль в `core.module_registry` на портале
- Собрал Docker-образ(ы) и запустил контейнер(ы)
- Создал nginx-конфиг `/etc/nginx/modules.d/mailer.conf` (на сервере)
- Если модуль с backend — поднял `pg-mailer` и сохранил DATABASE_URL в `core.module_secret`

После этого модуль уже доступен в портале — открыть `http://10.101.10.181:5000/mailer`.

---

## Цикл разработки

```
1. На вашей машине: правки кода → git commit → git push origin main
2. На портале (admin): /admin/deploy → найти карточку "mailer"
3. Pull → коммит появится в списке → Deploy → следить за логами
4. Deploy Agent делает всё остальное автоматически
```

### Если у модуля есть backend (`backend/` директория)

При каждом Deploy:

- Образ frontend пересобирается (Vite build → nginx со статикой)
- Образ backend пересобирается (Python + corper-shared + gunicorn)
- `alembic upgrade head` запускается внутри backend-контейнера — поэтому все ваши
  миграции **должны быть закоммичены** в `backend/alembic/versions/`
- nginx-конфиг перегенерируется на основе `module.json` (manifest)
- БД (`pg-mailer`) сохраняется между деплоями — volume не пересоздаётся

**Создать новую миграцию (на машине разработчика):**

Самый простой путь — через dev-стек (`docker-compose.dev.yml` в репо модуля
уже всё описывает):

```bash
# 1. Поднять локальный backend + db
docker compose -f docker-compose.dev.yml up -d backend db

# 2. Сгенерировать миграцию (автогенерация по diff моделей и схемы)
docker compose -f docker-compose.dev.yml exec backend \
    alembic revision --autogenerate -m "описание изменения"

# 3. Применить локально, чтобы проверить
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head

# 4. Закоммитить новый файл в backend/alembic/versions/
git add backend/alembic/versions/*.py
git commit -m "alembic: ..."
git push

# 5. На портале: /admin/deploy → модуль "mailer" → Deploy <commit>
#    Deploy Agent применит миграцию в prod БД автоматически.
```

Альтернатива: попросить super_admin запустить `alembic revision --autogenerate`
на портале и скопировать получившийся файл в свой репо. Полезно если у dev нет
docker.

---

## Что нужно сделать вручную (только один раз)

### 1. Добавить секцию в систему прав портала

Только если секция `notifications` ещё не зарегистрирована на портале.
Делается на **сервере портала**, не у вас.

В `corper-registry/models.py` добавить секцию `notifications` в подходящий модуль `MODULE_SECTIONS`,
а также в список `SECTIONS`:

```python
("notifications", "Служба рассылок"),
```

Затем на портале: `/admin/deploy` → Core Services → core-registry → Build & Deploy.

### 2. Выдать права пользователям

На портале (admin@... или super_admin@...):

1. Зайти в "Роли" → выбрать/создать роль
2. В конструкторе ролей появится секция "Служба рассылок"
3. Установить уровень доступа (none / user / admin)
4. Назначить роль сотрудникам

---

## Управление модулем (на портале)

Все операции через `/admin/deploy` → карточка модуля «mailer»:

| Действие | Что делает |
|----------|------------|
| **Pull** | `git pull origin main` в `/modules/mailer/` на сервере |
| **Deploy {commit}** | rebuild + restart контейнеров + alembic upgrade head + nginx reload |
| **Fix** | автоисправление (пересоздать контейнер, regenerate nginx) |
| **Logs** | хвост логов контейнера |
| **Migrate** | `alembic upgrade head` без пересборки (если у модуля есть backend) |
| **Delete** | снос контейнеров + nginx + deregister; `?drop_db=true` сносит и volume БД |

---

## Актуальная документация

Документация модулей обновляется централизованно. Скачать актуальную версию:

- **Правила разработки**: `http://10.101.10.181:5000/api/deploy/docs/public/templates/README.md`
- **API-контракт**: `http://10.101.10.181:5000/api/deploy/docs/public/templates/INTEGRATION.md`
- **Архитектура портала**: `http://10.101.10.181:5000/api/deploy/docs/public/architecture/CLAUDE.md`
- **Все документы**: `http://10.101.10.181:5000/api/deploy/docs/public`

Запрос AI-агенту: «Скачай актуальную документацию с
`http://10.101.10.181:5000/api/deploy/docs/public` и обнови README.md / DEPLOYMENT.md / INTEGRATION.md
в текущем модуле, сохраняя {{placeholders}} если они уже встречаются в тексте».
