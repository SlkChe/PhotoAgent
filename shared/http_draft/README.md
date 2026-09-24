# HTTP-кандидат B-01

Статус: предложение, не согласовано и не подключено к рабочему приложению.
[Спецификация, вопросы и сценарии](../../docs/mvp-1/http-contract-draft.md).

`operations.py` — тела мутаций, роли, отзывы, экспорт, статистика;
`session.py` — история, snapshot, выполнение; `validation.py` — связи примеров.
Использует утверждённые Answer/ApiError/ExecutionAccepted без изменения их схем.
Новый HTTP-конверт имеет отдельный contract_version=mvp1-http-draft.1.

Экспорт: `PYTHONPATH=. .venv/runtime-env/bin/python scripts/build_http_contract.py`.
Готовый документ: [OpenAPI](../../docs/mvp-1/http-contract-openapi.json).
[Примеры](../../docs/mvp-1/http-contract-examples.json) валидируются тестами.

Pydantic не заменяет авторизацию, проверку предыдущей версии, атомарность,
идемпотентность, бюджет и политику времени. Эти механизмы здесь не реализованы.
Модели нужны для ревью; стабильные имена/версия будут приняты после A-07/A-13.
