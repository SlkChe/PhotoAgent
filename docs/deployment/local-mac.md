# Dev и Stage на Mac

Назначение: исследовательский HTTPS-стенд D-01 и тестовый mock D-05.
Приложение пока использует протокол прототипа: эта инфраструктура не реализует
cookie/CSRF, восстановление и TTL MVP-1. Сквозная приёмка B-02 остаётся впереди.

## Предварительные условия

- Python 3.14 и `.venv/runtime-env` по корневому README.
- OpenSSL 3 для выпуска сертификатов (на текущем Mac `/opt/homebrew/bin/openssl`).
- Docker Desktop запущен. Для текущей установки добавить CLI и credential helper
  в PATH терминала:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

- Mac имеет закреплённый адрес `192.168.7.100`.
- В hosts клиента оба имени указывают на этот адрес:

```text
192.168.7.100 photoagent-dev.home.arpa
192.168.7.100 photoagent-stage.home.arpa
```

- Для публикации 443 на конкретном IP в Docker Desktop включается privileged
  port mapping. Если отсутствует `/var/run/com.docker.vmnetd.sock`, проверить
  установку штатного помощника. Владелец при необходимости выполняет локально:

```bash
sudo /Applications/Docker.app/Contents/MacOS/install vmnetd
```

Все дальнейшие команды — из корня проекта. Локальные файлы с секретами не
включаются в Git, сборку, архивы передачи и диагностические отчёты.

## Сертификаты

Только при первом создании комплекта:

```bash
bash scripts/create_local_tls.sh
```

Скрипт создаёт EC P-256 CA на 5 лет и отдельные сертификаты Dev/Stage на 90 дней,
проверяет назначение serverAuth, цепочку и DNS-имена. Каталоги имеют права 700,
файлы — 600. Существующие ключи/сертификаты не перезаписываются; повторный запуск
завершается отказом. Не удалять CA ради повторного запуска: это потребует повторной
настройки доверия на клиентах. Процедура продления — отдельная операция до истечения
90 дней с сохранением CA и контролируемой заменой серверных файлов.

Публичный CA: `.devsec/ssl/ca/ca.crt`. Приватный ключ CA остаётся только на Mac
и не монтируется в ingress. Серверные файлы — в `.devsec/ssl/dev/` и `stage/`.
Системное действие настройки доверия после проверки отпечатка:

```bash
openssl x509 -in .devsec/ssl/ca/ca.crt -noout -sha256 -fingerprint
security add-trusted-cert -r trustRoot -p ssl \
  -k "$HOME/Library/Keychains/login.keychain-db" .devsec/ssl/ca/ca.crt
```

На другие устройства переносится только публичный сертификат CA. Для Python/curl
можно явно указать его как доверенный CA; отключение TLS-проверки не требуется.
Доверие Firefox/Android и сетевой доступ других устройств проверяются отдельно.

## Запуск Dev

API и UI запускаются в двух терминалах, останавливаются `Ctrl+C` в соответствующем:

```bash
.venv/runtime-env/bin/python scripts/run_dev.py api
```

```bash
.venv/runtime-env/bin/python scripts/run_dev.py ui
```

API слушает `127.0.0.1:8000`, UI — `127.0.0.1:8501`. Скрипт передаёт каждому
процессу его `PHOTO_API_*` либо `PHOTO_UI_*` и минимальное системное окружение.
Секреты из `.devsec/.env.local` пока не загружаются: текущему прототипу они не нужны.
Ключи провайдеров автоматически не наследуются; подключение интеграций требует
явного дополнения разрешённого набора параметров backend.

```bash
docker compose -f docker/compose.local.yaml up -d ingress
```

Открыть `https://photoagent-dev.home.arpa`: ожидается существующий чат прототипа.
Ingress обращается к Dev через `host.docker.internal`. Прямые API-маршруты сессий,
Swagger и OpenAPI через ingress закрыты; разрешены `/health` и POST-сигнал
`/sessions/{uuid}/close` текущего прототипа с проверкой Origin.
Это временный список маршрутов, не реализация будущего браузерного API MVP-1.

### Быстрая остановка Dev

1. Нажать `Ctrl+C` в терминале API (`run_dev.py api`).
2. Нажать `Ctrl+C` в терминале UI (`run_dev.py ui`).
3. Если Stage тоже остановлен, остановить общий HTTPS ingress:

```bash
docker compose -f docker/compose.local.yaml stop ingress
```

Если Stage продолжает работать, ingress оставить включённым. После остановки
Dev порты 8000/8501 освобождаются, RAM-сессии Dev теряются. При работающем ingress
Dev-адрес может возвращать 502, поскольку его локальные сервисы остановлены.
Команды Docker сами по себе локальные процессы Python не останавливают.

Если сервисы запускал агент, IDE или другой терминал, сначала определить процессы:

```bash
lsof -nP -iTCP:8000 -iTCP:8501 -sTCP:LISTEN
```

Проверить команду и рабочий каталог каждого найденного PID через
`ps -p PID -o pid,ppid,command` и `lsof -a -p PID -d cwd`.
Только для подтверждённых процессов этого проекта выполнить `kill -TERM PID`,
подставив фактический PID. Не использовать массовый `killall python` или `pkill`:
они могут остановить другие приложения. Если процесс возвращается, остановить
его через запустившую IDE или управляющий процесс.

## Запуск Stage

```bash
docker compose -f docker/compose.local.yaml --profile stage build
docker compose -f docker/compose.local.yaml --profile stage up -d --no-build
docker compose -f docker/compose.local.yaml --profile stage ps
```

Открыть `https://photoagent-stage.home.arpa`. API/UI Stage не публикуют порты
на хост и не монтируют рабочее дерево; правки Dev не меняют уже собранную Stage.
Ingress общий для Dev/Stage, использует только серверные сертификаты на чтение.
CA и секреты приложения ему недоступны. Проверка health ingress подтверждает
только слушающий TLS-порт; доступность upstream проверяется отдельно.

Проверка TLS и API без изменения доверия Python/curl:

```bash
curl --noproxy '*' --cacert .devsec/ssl/ca/ca.crt https://photoagent-dev.home.arpa/health
curl --noproxy '*' --cacert .devsec/ssl/ca/ca.crt https://photoagent-stage.home.arpa/health
```

Ожидается `{"status":"ok"}`. Для временной диагностики без privileged helper
можно задать `PHOTO_HTTPS_PORT=8443` перед командой Compose и обращаться к `:8443`;
это не штатный режим браузерной проверки: публичные URL UI и Origin рассчитаны на 443.

После настройки доверия CA в macOS и при установленном Chrome:

```bash
.venv/runtime-env/bin/python scripts/check_https.py
```

Проверяются оба окружения, TLS, закрытые маршруты API и ответ чата через WSS;
флаг отключения проверки сертификатов не используется.

Логи Stage:

```bash
docker compose -f docker/compose.local.yaml --profile stage logs --tail 50 stage-api stage-ui
```

Access logs API и ingress отключены; ingress не выводит ошибки с потенциальными URL/токенами,
поэтому диагностика выполняется через health и воспроизводимые синтетические пробы.
Перезапуск API теряет RAM-сессии; обновление Stage выполнять в согласованное время.

### Быстрая остановка Stage

```bash
docker compose -f docker/compose.local.yaml --profile stage stop stage-ui stage-api
```

Останавливаются только контейнеры `stage-ui` и `stage-api`. Общий ingress остаётся
работать для Dev. Если Dev также остановлен:

```bash
docker compose -f docker/compose.local.yaml stop ingress
```

RAM-сессии Stage теряются. Контейнеры и образы сохраняются для повторного запуска
через команду `up -d --no-build` из раздела запуска Stage. Пока ingress работает,
Stage-адрес после остановки его сервисов может возвращать 502.
LiteLLM — отдельный стенд, остановка Dev/Stage его не затрагивает.

## D-05: изолированный LiteLLM

```bash
docker compose -f docker/compose.test.yaml --profile test up -d
docker compose -f docker/compose.test.yaml --profile test ps
.venv/runtime-env/bin/python scripts/check_mock.py
```

Клиентский `base_url`: `http://127.0.0.1:4000/v1`; рабочий API-ключ не нужен.
Применяется фиксированный ARM64-образ LiteLLM 1.102.1 с digest в Compose;
его Python/runtime поставляются upstream и не заменяют Python 3.14 приложения.
Образ не устанавливает зависимости в локальное окружение проекта.

Для непокрытых штатным proxy сценариев подготовлена собственная тестовая
HTTP-обвязка SDK (`docker/test/litellm_mock`). Она вызывает только `mock_completion`,
не `completion` и не router. Это кандидат для согласования с backend/QA, не
утверждённый production-компонент. `docker/test/litellm-proxy.yaml` сохраняет
конфигурацию отдельной исследовательской пробы штатного proxy.

Сценарий выбирается полем `model`: `echo`, `fixture`, `rate-limit`, `server-error`,
`delay`, `malformed-json`, `length`, `missing-usage`, `invalid-usage`.
Echo отражает последний user.content; прочие успешные сценарии используют
`tests/fixtures/llm-draft.json`. Это синтетический черновик DevOps, его предметный
формат и пригодность для B-09 должен подтвердить backend. Streaming не поддерживается.
Никакие параметры внешнего провайдера/base_url в запросе не принимаются.

```bash
curl --noproxy '*' http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"echo","messages":[{"role":"user","content":"Тест"}]}'
curl --noproxy '*' http://127.0.0.1:4000/__test/state
curl --noproxy '*' -X POST http://127.0.0.1:4000/__test/reset
```

Счётчик считает принятые completion-запросы, включая 429/503/timeout; невалидный
запрос с 422 не считается. Параллельные наборы тестов должны использовать отдельные
экземпляры стенда либо согласованный сброс. При перезапуске счётчик обнуляется.
Данные запросов не сохраняются, access log отключён. Только синтетические данные.

LiteLLM подключён только к сети `internal: true`, без внешнего маршрута.
HTTP-relay подключён также к сети доступа и публикует только loopback:4000;
он проксирует фиксированный адрес mock и не предоставляет общий сетевой прокси.
Отдельный relay нужен, поскольку проверенная версия Engine не публикует порт
контейнера, подключённого только к internal-сети. Ключи/секретные тома отсутствуют.

```bash
docker compose -f docker/compose.test.yaml --profile test logs --tail 50
docker compose -f docker/compose.test.yaml --profile test restart litellm
```

Обычный корневой `docker compose up` mock не включает. Без профиля `test` отдельный
тестовый Compose также не включает сервисы. Приёмка QA и проверки клиентского
адаптера backend выполняются отдельно; этот стенд не подтверждает качество Groq.

### Быстрая остановка LiteLLM

```bash
docker compose -f docker/compose.test.yaml --profile test stop mock-relay litellm
```

Останавливаются два контейнера тестового стенда, порт 4000 освобождается.
Счётчик mock сбрасывается при следующем запуске. Dev и Stage продолжают работать.

## Полная остановка стендов на Mac

Чтобы завершить все процессы PhotoAgent и освободить занятые ими ресурсы:

1. Остановить локальные API и UI Dev по разделу
   [«Быстрая остановка Dev»](#быстрая-остановка-dev).
2. Остановить все пять контейнеров двух Compose-проектов:

```bash
docker compose -f docker/compose.local.yaml --profile stage stop
docker compose -f docker/compose.test.yaml --profile test stop
```

| Компонент | Что должно быть остановлено |
|---|---|
| Локальный Dev | Процессы Uvicorn API и Streamlit UI на 8000/8501 |
| Общий HTTPS | Контейнер `ingress`, публикация 443 (либо временного 8443) |
| Stage | Контейнеры `stage-api`, `stage-ui` |
| D-05 | Контейнеры `litellm`, `mock-relay`, публикация 4000 |

Если дополнительно запускался прежний прототип из корневого `compose.yaml`,
остановить его отдельно командой `docker compose stop` из корня проекта.

Проверка перед выходом из Docker Desktop:

```bash
docker compose -f docker/compose.local.yaml --profile stage ps --status running
docker compose -f docker/compose.test.yaml --profile test ps --status running
lsof -nP -iTCP:443 -iTCP:8443 -iTCP:8000 -iTCP:8501 -iTCP:4000 -sTCP:LISTEN
```

В первых двух списках не должно быть работающих контейнеров. Порты, занятые
PhotoAgent, должны освободиться; если `lsof` показывает процесс, проверить владельца,
а не завершать его автоматически. Отсутствие совпадений у `lsof` даёт код возврата 1
и в этом случае является ожидаемым результатом.

Для освобождения ресурсов самой Linux VM выбрать **Quit Docker Desktop** в меню
Docker Desktop. Закрытие окна приложения не равнозначно выходу. Выход остановит
также контейнеры других проектов, если они работают. Для следующего запуска
стендов сначала запустить Docker Desktop.

### Что остаётся после остановки

Остановка возвращает Mac в состояние без работающих сервисов PhotoAgent.
Она сохраняет образы, остановленные контейнеры, сети, виртуальное окружение,
файлы проекта и `.devsec/`, записи hosts и доверие к локальному CA.
Системный помощник Docker `vmnetd` может оставаться установленным и запущенным;
это отдельный системный сервис, а не контейнер PhotoAgent.

Для обычного завершения работы удалять эти настройки не требуется. Полный возврат
к состоянию до установки стенда означает отдельный демонтаж: отзыв доверия CA,
удаление только добавленных записей hosts, согласованное удаление локальных ключей
и Docker-ресурсов, при необходимости удаление Docker Desktop и его помощника.
Такие изменения выполняются отдельно после согласования с владельцем.

Если нужно убрать остановленные контейнеры и сети проекта, вместо `stop` можно
использовать `down` с теми же `-f` и `--profile`. Это не удаляет образы, `.devsec/`
и системные настройки. Флаг `-v` не добавлять без согласования удаления томов.
