# AI Code Audit — от плохого кода к рабочему сервису

Домашнее задание «Кейс 3: AI для кода». Берём намеренно плохой Flask-сервис, проводим аудит с помощью AI, исправляем найденное, покрываем тестами и упаковываем в Docker.

История коммитов повторяет путь работы:

| Коммит | Этап |
|---|---|
| `initial: legacy code before audit` | исходный код с ошибками в `legacy/` |
| `docs: audit report` | аудит — [AUDIT.md](AUDIT.md) |
| `refactor: fix audit findings` | исправленный сервис в `app/` |
| `test: add pytest and endpoint checker` | тесты и проверка живого сервера |
| `docs: README, requirements, OpenAPI` | документация и зависимости |
| `fix: keep /slow non-blocking ...` | исправление, найденное при проверке в Docker |
| `build: Dockerfile and compose` | контейнеризация |
| `ci: GitHub Actions` | автоматическая проверка: ruff, pytest, docker build |

## Структура

```
ai-code-audit/
├── legacy/                 # «до»: код с ошибками, оставлен без изменений
│   ├── utils.py
│   └── api.py
├── app/                    # «после»: исправленный сервис
│   ├── __init__.py         # create_app(), JSON-обработчики ошибок
│   ├── db.py               # подключение к SQLite, init_db, соединение на запрос
│   ├── models.py           # User, валидация AddUserRequest
│   ├── services.py         # пользователи, пароли (PBKDF2), ActiveUsers, фоновые задачи
│   └── routes.py           # Blueprint с эндпоинтами
├── tests/test_api.py       # pytest: все эндпоинты, SQL-инъекции, 100 потоков
├── scripts/check_endpoints.py  # проверка живого сервера
├── run.py                  # точка входа для gunicorn и локального запуска
├── openapi.yaml            # спецификация OpenAPI 3.1
├── AUDIT.md                # отчёт аудита
├── Dockerfile, docker-compose.yml, .dockerignore
└── requirements.txt, requirements-dev.txt, pyproject.toml
```

## Что было найдено при аудите

40 проблем, из них 16 критических или высоких. Полная таблица с номерами строк — в [AUDIT.md](AUDIT.md).

- **SQL-инъекции в четырёх местах** — f-строка, `%` и конкатенация. На живом legacy-коде `/user/0 UNION SELECT ...` вытащил схему БД, а `/adduser` позволил вставить лишнюю запись `hacked`.
- **«Хеширование» пароля разворотом строки** и хранение в открытом `passwords.txt`.
- **`is_admin` с голым `except`, возвращающий `True`** — любая ошибка давала права администратора.
- **`debug=True` на `0.0.0.0`** — отладчик Werkzeug, то есть удалённое выполнение кода.
- **Гонки** — общий список активных пользователей без блокировок, одно соединение SQLite на все потоки.
- **Баги** — мутируемый аргумент по умолчанию, `int + ""`, `{}` вместо `None`, 500 вместо 404, 201 вместо 200, `NameError` в обработчике ошибки.
- **Ресурсы** — незакрытые соединения и файлы, `/slow` блокирует воркер на десятки секунд.
- **Стиль** — `addUser`, `GETUSER`, однобуквенные имена, нарушения PEP 8.

Что сделано в `app/`: только параметризованные запросы, соединение на запрос через `flask.g` и `teardown_appcontext`, PBKDF2-HMAC-SHA256 с солью, `ActiveUsers` с `threading.Lock`, валидация входа, фоновые задачи в пуле потоков, JSON-ответы для всех ошибок, путь к БД из переменной `DB_PATH`. Код проходит `ruff` с правилами PEP 8, безопасности (bandit) и docstrings.

Про `/slow`: задача выполняется в фоновом потоке, и ответ 202 приходит за десятки миллисекунд. Потоки Python делят GIL, поэтому, пока задача считает, остальные запросы замедляются. Для настоящих CPU-тяжёлых задач в продакшене нужен пул процессов или очередь задач (Celery, RQ).

## Локальный запуск

Нужен Python 3.11 или новее.

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python run.py                       # http://127.0.0.1:8080
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python run.py
```

База создаётся в `data/app.db`. Другой путь задаётся переменной окружения:

```bash
DB_PATH=/tmp/users.db python run.py           # Linux / macOS
$env:DB_PATH="C:\temp\users.db"; python run.py  # Windows PowerShell
```

Для продакшен-режима на Linux и macOS: `gunicorn -b 0.0.0.0:8080 run:app`.

## Тесты и проверки

```bash
ruff check .                         # линтер
pytest -v                            # 44 теста
python scripts/check_endpoints.py    # проверка живого сервера, по умолчанию http://localhost:8080
python scripts/check_endpoints.py http://example.com:8080
BASE_URL=http://example.com:8080 python scripts/check_endpoints.py
```

Скрипт печатает таблицу «эндпоинт / ожидаемый / фактический / OK или FAIL» и завершается с кодом 1, если хотя бы одна проверка не прошла.

## Запуск в Docker

```bash
docker build -t ai-code-audit .
docker run --rm -d -p 8080:8080 --name audit ai-code-audit
python scripts/check_endpoints.py
docker stop audit
```

Или через Compose, с именованным томом для базы:

```bash
docker compose up -d --build
docker compose down          # данные остаются в томе audit-data
docker compose down -v       # удалить вместе с данными
```

Образ собирается в две стадии на `python:3.12-slim`, работает от непривилегированного пользователя, проверяет себя через `HEALTHCHECK` на `/health` и хранит базу в томе `/app/data`.

## Эндпоинты

Полная спецификация — в [openapi.yaml](openapi.yaml), её можно открыть в [Swagger Editor](https://editor.swagger.io/).

| Метод | Путь | Успех | Ошибки | Описание |
|---|---|---|---|---|
| POST | `/adduser` | 201 | 400, 405 | создать пользователя |
| GET | `/user/<uid>` | 200 | 404 | получить пользователя |
| GET | `/activate/<uid>` | 200 | 404 | отметить активным, вернуть последние 5 |
| GET | `/slow` | 202 | — | запустить тяжёлую задачу в фоне |
| GET | `/wrong` | — | 500 | пример обработанной ошибки |
| GET | `/health` | 200 | 500 | проверка сервиса и БД |

Примеры:

```bash
curl -i -X POST http://localhost:8080/adduser \
     -H "Content-Type: application/json" -d '{"name": "alice", "tags": ["dev"]}'
# 201 {"status":"created","id":1,"name":"alice"}

curl -i -X POST http://localhost:8080/adduser \
     -H "Content-Type: application/json" -d '{"name": ""}'
# 400 {"error":"validation_error","detail":"name must not be empty"}

curl -i http://localhost:8080/user/1
# 200 {"id":1,"name":"alice","tags":["dev"]}

curl -i http://localhost:8080/user/999
# 404 {"error":"not_found"}

curl -i http://localhost:8080/activate/1
# 200 {"active":[1]}

curl -i http://localhost:8080/slow
# 202 {"status":"scheduled"}

curl -i http://localhost:8080/wrong
# 500 {"msg":"error","detail":"division by zero"}

curl -i http://localhost:8080/health
# 200 {"status":"ok"}
```

В Windows PowerShell вместо `curl` с JSON удобнее `Invoke-RestMethod`:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8080/adduser `
  -ContentType "application/json" -Body '{"name": "alice"}'
```

## Docker Hub и сервер

Публикация образа (вместо `<DOCKERHUB_USER>` — свой логин на Docker Hub):

```bash
docker login
docker tag ai-code-audit <DOCKERHUB_USER>/ai-code-audit:latest
docker push <DOCKERHUB_USER>/ai-code-audit:latest
```

Если сборка идёт на Mac с Apple Silicon, а сервер на x86_64, собирайте образ под обе платформы:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t <DOCKERHUB_USER>/ai-code-audit:latest --push .
```

Установка Docker на сервер с Ubuntu (официальный репозиторий Docker):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER    # перелогиньтесь, чтобы работать без sudo
```

Запуск на сервере:

```bash
docker pull <DOCKERHUB_USER>/ai-code-audit:latest
docker run -d --restart unless-stopped \
  -p 8080:8080 \
  -v audit-data:/app/data \
  --name audit \
  <DOCKERHUB_USER>/ai-code-audit:latest

docker ps                                   # STATUS должен стать (healthy)
curl http://localhost:8080/health
```

Если на сервере включён `ufw`, откройте порт: `sudo ufw allow 8080/tcp`.

Обновление до новой версии:

```bash
docker pull <DOCKERHUB_USER>/ai-code-audit:latest
docker rm -f audit
# и снова команда docker run выше — данные сохранятся в томе audit-data
```
