# PhotoAgent

Прототип ассистента фотографа: Streamlit-чат, FastAPI-сессии и обработчики тем.
Внешние ИИ и поиск пока не вызываются, файлы не загружаются. API возвращает названия
тем: подтверждение, поиск оборудования или услуг, теория, вопросы к конкретным кадрам.
Одна реплика может относиться к нескольким темам. Нераспознанная реплика получает
ответ «Тема не определена». Классификация эвристическая, без обещания точности ИИ.

## Локальный запуск

Нужен Python 3.14. Команды выполняются из корня репозитория.

```bash
python3.14 -m venv .venv/runtime-env
source .venv/runtime-env/bin/activate
python -m pip install -r requirements-dev.txt
```

В текущем рабочем каталоге это окружение Python 3.14 уже подготовлено:
достаточно выполнить `source .venv/runtime-env/bin/activate`.

В первом терминале запустите API:

```bash
PYTHONPATH=.:core-api python -m uvicorn photo_api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Во втором терминале активируйте то же окружение и запустите UI:

```bash
source .venv/runtime-env/bin/activate
export PHOTO_UI_BACKEND_URL=http://127.0.0.1:8000
export PHOTO_UI_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
PYTHONPATH=.:streamlit-ui python -m streamlit run streamlit-ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Откройте http://127.0.0.1:8501. Swagger: http://127.0.0.1:8000/docs.
Для отладки в IDE используйте модуль `uvicorn` с теми же аргументами, но без
`--reload`; рабочая директория — корень проекта, `PYTHONPATH=.:core-api`.
Секреты прототипу не нужны. `.env` автоматически не читается; `.env.example`
документирует только имена параметров и безопасные примеры.

## Проверка

```bash
PYTHONPATH=.:core-api:streamlit-ui python -m unittest discover -s ./tests -p '*_test.py'
ruff check .
ruff format --check .
```

Один файл: `PYTHONPATH=.:core-api:streamlit-ui python -m unittest discover -s ./tests -p 'api_test.py'`.

При работающих сервисах и установленном Google Chrome доступна браузерная проверка:

```bash
python scripts/browser_check.py --ui-url http://127.0.0.1:8501 --api-url http://127.0.0.1:8000
```

Она проверяет чат и сигнал закрытия страницы, сохраняет снимки интерфейса в `docs/`.

Ручной сценарий: отправьте «Объясни диафрагму», затем «Да, продолжай», затем
«А почему?». Ожидаются теория, утвердительный ответ и снова теория. Нажмите
«Новый чат»: лента очищается, прежняя сессия удаляется. Карточка поиска возвращает
«Поиск оборудования или услуг», вопрос «Почему на этом кадре смазан фон?» — тему кадров.

## Docker Compose

Для локального Dev с HTTPS, контейнерного Stage и изолированного LiteLLM
используйте [инструкцию стенда на Mac](docs/deployment/local-mac.md).
Результаты проверок и оставшиеся условия приёмки —
[D-01/D-05](docs/mvp-1/deployment-checks.md).
Команды ниже сохраняют прежний запуск прототипа без ingress.

```bash
docker compose up -d --build
docker compose logs -f core-api
docker compose down
```

Сервисы публикуются только на локальном интерфейсе. При изменении `BACKEND_PORT`
также задайте `PHOTO_UI_PUBLIC_BACKEND_URL` с новым портом. Внутренний адрес
`PHOTO_UI_BACKEND_URL` в Compose используется сервером Streamlit;
`PHOTO_UI_PUBLIC_BACKEND_URL` должен быть доступен браузеру для сигнала закрытия.

## Контракты API

| Метод | Путь | Результат |
|---|---|---|
| POST | `/sessions` | Новая сессия, 201 |
| GET | `/sessions/{id}` | Контекст и срок жизни |
| POST | `/sessions/{id}/messages` | Реплика `{request_id, text}` → `{request_id, topics, reply}` |
| POST | `/sessions/{id}/heartbeat` | Продление открытого чата |
| DELETE | `/sessions/{id}` | Удаление контекста, 204 |
| POST | `/sessions/{id}/close` | Удаление через браузерный сигнал, 204 |
| GET | `/health` | Доступность API |

## Жизненный цикл и ограничения

- Контекст хранится только в памяти одного процесса API. Запускайте один worker;
  перезапуск API или `--reload` удаляет сессии. БД и кеширования нет.
- UI держит копию реплик для отрисовки только в `st.session_state`. Архива,
  восстановления истории, cookies и localStorage для диалога нет.
- Пока вкладка активна, UI отправляет heartbeat каждые 20 секунд. Без него сессия
  истекает через 180 секунд; фоновая очистка выполняется каждые 10 секунд.
- При `pagehide` браузер пытается отправить `sendBeacon` для немедленного удаления.
  При аварийном закрытии, потере сети или остановке UI гарантируется очистка по
  сроку жизни, пока API работает. Мгновенное удаление при любом закрытии браузера
  гарантировать нельзя. Замороженная фоновая вкладка также может потерять сессию.
- По умолчанию: 1000 активных сессий, 100 пар реплик в сессии, 4000 символов в запросе.
  Лимиты и интервалы задаются окружением. Heartbeat должен быть существенно короче TTL.
- Прототип предназначен для локальной отладки без авторизации. Случайный ID сессии
  даёт доступ к её контексту; API не следует публиковать в интернете в таком виде.

Структура: `core-api/photo_api`, `streamlit-ui/photo_ui`, общие схемы `shared`,
проверки `tests`, Dockerfile в `docker`.
Концепт интерфейса: [docs/ui/concept.md](docs/ui/concept.md).
