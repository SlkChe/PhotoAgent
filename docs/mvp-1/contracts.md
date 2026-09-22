# A-05. Предметные контракты MVP-1

Дата: 2026-09-21. Статус: **архитектурные контракты версии 1.0 утверждены; A-05 закрыта**.
Связан с [архитектурой](architect.md). Это спецификация полей, связей и инвариантов.
Реализация Pydantic/JSON Schema и OpenAPI — последующая работа; она должна сохранять
эти правила. Настраиваемые количественные лимиты выбираются по измерениям
для согласованных 2–3 одновременно работающих пользователей.
QueryAnalysis и SearchPlan формируются строго локально, без облачного резерва.
Восстановление выполнения после обновления страницы и серверный TTL 12 часов
описаны в [жизненном цикле сессии](session-lifecycle.md).
Согласованы восстановление через защищённую cookie и продление TTL только действиями
пользователя. Чтение состояния выполнения не изменяет last_activity_at и expires_at;
повтор доставки request_id не является новой активностью.

## Общие правила

Четыре корневых объекта содержат `schema_version: "1.0"`, `session_id: UUID`,
`request_id: UUID`, `execution_id: UUID`. В MVP-1 сессия представляет анонимного
пользователя и является владельцем запроса. Отдельный user_id не вводится.
Это идентичность в пределах сессии, а не распознавание человека между браузерами
или после удаления сессии.

Клиент создаёт request_id до отправки и повторно использует его при повторной
доставке той же реплики. API создаёт session_id, execution_id и answer_id.
Идентификаторы объектов планирования и Evidence назначает или нормализует backend.
Ключ принадлежности и защиты от дублей — **(session_id, request_id)**.
Одинаковый request_id в разных сессиях обозначает разные запросы.
Сессия определяется по проверенному токену доступа, не по доверенному на слово ID
из тела запроса. Доступ ко всем связанным выполнениям и ответам проверяется
по этой сессии; UUID сам по себе не является средством авторизации.

Служебный конверт session_id/request_id/execution_id заполняет оркестратор.
Модель не выбирает и не меняет владельца; этот конверт не требуется передавать
внешним поисковикам или генератору. Неизвестные поля запрещены; обязательны все перечисленные
поля, если явно не указано иное. `T | null` означает обязательное поле с допустимым
пустым значением; списки могут быть пустыми, если ниже не указан минимум.
Время получения и выполнения — ISO 8601 UTC; неизвестные сведения — `null`,
не выдуманная дата или пустая строка. UUID и ссылки проверяются программно.
Внутренние диагностические сведения не отправляются целиком в UI.

При повторе ключа с тем же текстом и исходными настройками вернуть прежнее
выполнение/результат. При другом содержимом вернуть HTTP 409 с кодом
`request_id_conflict`. Сравнивается сохранённый нормализованный текст (удалены
краевые пробелы, регистр и пунктуация сохранены) и снимок настроек принятой отправки.
Клиент сохраняет этот снимок при retry. Новая реплика, в том числе ответ на
уточнение, получает новый request_id. Связь с исходным уточняемым вопросом и счётчик
раундов ведёт оркестратор. После очистки/TTL/перезапуска API ключи и результаты
исчезают вместе с сессией; межсессионное восстановление дублей не обещается.

`Topic` и `Intent` — закрытые перечисления A-03. `Entity`:
`entity_id: string`, `kind: person|organization|work|technology|movement|genre|place`,
`label: string`, `aliases: string[]`, `external_id: string|null`.
Локальный ID сущности не означает подтверждённую идентификацию во внешнем справочнике.
`TimeScope`: `label: string`, `start_year: int|null`, `end_year: int|null`;
неизвестные границы допустимы, известное начало не позже конца. Историческая
неточность сохраняется в label, не преобразуется в точную дату.

## QueryAnalysis

Производитель: локальный анализатор и проверяющий код. Потребитель: оркестратор.
Основной intent отражает явно указанную пользователем главную задачу; если её нет,
берётся intent первого содержательного подвопроса в порядке запроса. Остальные
задачи сохраняются в subquestions, даже при response_mode=thematic_overview.

| Поле | Тип и смысл |
|---|---|
| `intent` | `Intent | null`; null допустим для чистой управляющей/непонятной реплики |
| `dialogue_act` | `ask | confirm | clarification_reply | rephrase | change_subject | cancel` |
| `response_mode` | `focused | thematic_overview`; способ организации ответа, отдельно от intent |
| `topics` | Уникальный `Topic[]`; минимум одна для содержательного вопроса в границах |
| `entities` | `Entity[]` |
| `time_scope` | `TimeScope | null` |
| `geography` | `string[]`; явно заданные или разрешённые из контекста места |
| `subquestions` | `Subquestion[]`; минимум один для нового поиска |
| `ambiguities` | `Ambiguity[]` |
| `needs_clarification` | `bool`, согласован с clarification |
| `clarification` | `Clarification | null` |
| `in_scope` | `bool`; true при наличии хотя бы одной допустимой содержательной части |
| `scope_status` | `in_scope | mixed | out_of_scope | undetermined`; undetermined для управляющей/непонятной реплики |
| `excluded_parts` | `string[]`, обязательное объяснение исключённых частей при mixed/out_of_scope |
| `context_update` | `ContextUpdate`; предложение, которое проверяет оркестратор |

`Subquestion`: `id: string`, `text: string`, `intent: Intent`, `topics: Topic[]`,
`entity_ids: string[]`. Подвопросы принадлежат только допустимой части запроса.

`Ambiguity`: `id: string`, `description: string`, `candidate_labels: string[]`,
`blocks_answer: bool`. `Clarification`: `id: string`, `question: string`,
`ambiguity_ids: string[]`, `options: string[]`; один вопрос, свободный ответ допустим.

`ContextUpdate`: `base_revision: int`, `subject_action: keep|replace`,
`active_entity_ids: string[]`, `time_scope: TimeScope|null`, `geography: string[]`,
`pending_action: string|null`. Это желаемый контекст, не произвольный JSON patch.
Ссылки на сущности должны существовать в анализе или текущей версии сессии.

Инварианты: `needs_clarification` равен наличию `clarification`; уточнение ссылается
на блокирующую неоднозначность. При уточнении либо полностью исключённом вопросе
поиск не запускается. Для `mixed` in_scope=true; для `out_of_scope` и `undetermined`
in_scope=false. Управляющие реплики обрабатываются по dialogue_act до scope_status,
поэтому «объясни проще» не превращается в отказ по тематике.
Для широкого вопроса или нескольких вопросов одной темы response_mode=thematic_overview;
intent подвопросов сохраняются, чтобы обзор не потерял сравнение или проверку тезиса.
Счётчик раундов уточнения хранит оркестратор: максимум один на исходный запрос,
модель не может сбросить его обновлением context_update. `cancel` относится
к ожидающему уточнению; отдельная отмена активного выполнения в минимальном UI не требуется.

Согласованное поведение занятой сессии: HTTP 409 с кодом `session_busy`,
`session_status: in_progress` и `active_execution_id`. Значение in_progress
отображает состояние диалога processing. Схема ошибки определена ниже;
проверка request_id предшествует проверке занятости. Отклонённая новая реплика
не меняет историю и TTL. В состоянии обработки UI блокирует ввод и отправку.

## SearchPlan

Производитель: планировщик, после проверки политик. Потребитель: Gateway.

| Поле | Тип и смысл |
|---|---|
| `plan_id` | `UUID` |
| `steps` | Непустой `SearchStep[]` |
| `deadline_at` | Предельное время завершения поиска, UTC |
| `max_external_calls` | Положительное целое; включает повторы и чтение документов |
| `max_total_text_chars` | Положительное целое; суммарный предел входных текстов |
| `max_evidence_fragments` | Положительное целое |

`SearchStep`: `step_id: string`, `subquestion_ids: string[]`,
`tool_id: string`, `operation: search|fetch|entity_lookup`, `queries: string[]`,
`languages: string[]`, `preferred_source_types: string[]`, `depends_on: string[]`,
`input_source_ids: string[]`, `max_results: int`, `timeout_ms: int`.
Числовые лимиты положительные; tool_id и операции разрешены реестром.
Поисковые варианты включают оригинальные имена, если они известны.
Fetch получает ID источников из предшествующих результатов, не придуманный URL;
при зависимом шаге конкретные ID связывает Gateway после завершения depends_on.

План — конечный ациклический граф. Каждый подвопрос покрывается хотя бы одним шагом.
Ошибки отдельных шагов не означают успех: их причины переходят в Evidence.gaps.
Пределы плана не выше общего бюджета выполнения. Стоимость генерации и токены
контролируются общим бюджетом оркестратора, за пределами SearchPlan.
Адаптер преобразует типизированный шаг в параметры конкретного MCP/API;
произвольного словаря команд от модели нет.

## Evidence

Производитель: Evidence Builder. Потребители: генератор, валидатор и сборщик UI.

| Поле | Тип и смысл |
|---|---|
| `evidence_id` | `UUID` |
| `plan_id` | `UUID | null`; null при использовании Evidence предыдущего ответа |
| `sources` | `Source[]` |
| `fragments` | `Fragment[]` |
| `coverage` | `Coverage[]`, запись для каждого подвопроса |
| `conflicts` | `Conflict[]` |
| `gaps` | `Gap[]` |
| `retrieval_status` | `complete | partial | empty | failed`; complete означает исполненный поиск, не полноту знаний |

`Source`: `source_id: string`, `url: HTTPS/HTTP URL`, `title: string`,
`author_or_organization: string|null`, `published_date: string|null`,
`retrieved_at: UTC datetime`, `source_type: primary|secondary|encyclopedia|other`,
`access_mode: full_text|excerpt|snippet`, `provider_id: string`,
`origin_group: string|null`, `usage_constraints: string[]`.
Дата публикации сохраняет доступную точность. Источники с общим origin_group
не считаются независимыми; null означает неизвестное происхождение, не независимость.

`Fragment`: `fragment_id: string`, `source_id: string`, `text: string`,
`locator: string|null`, `subquestion_ids: string[]`.
Текст — действительно полученный фрагмент; перевод/пересказ не выдаётся за оригинал.
Locator — страница, раздел либо другая доступная привязка.

`Coverage`: `subquestion_id: string`, `status: sufficient|limited|missing`,
`fragment_ids: string[]`. Это оценка покрытия, а не вероятность истинности.
`Conflict`: `conflict_id: string`, `subquestion_id: string`, `description: string`,
`versions: ConflictVersion[]` (минимум две).
`ConflictVersion`: `statement: string`, `fragment_ids: string[]` (непустой).
`Gap`: `subquestion_id: string|null`,
`reason: no_results|timeout|provider_error|snippet_only|budget_exhausted|unresolved_identity|restricted_access`,
`description: string`.

Все ссылки на ID разрешаются внутри пакета или явно выбранных Evidence той же
сессии. При reuse создаётся новый пакет с нужными источниками и исходным retrieved_at.
Не объявлять свежий поиск выполненным. Дедупликация не уничтожает атрибуцию.
Наличие двух доменов не считается доказательством независимости.

## Answer

Производитель: backend после генерации и проверки либо детерминированного ответа.
Потребитель: UI. Генератор предлагает содержательные поля, но не доверенные URL/ID.

| Поле | Тип и смысл |
|---|---|
| `answer_id` | `UUID` |
| `kind` | `answer | clarification | out_of_scope | insufficient_evidence` |
| `completeness` | `complete | limited | not_applicable` |
| `direct_answer` | Непустая строка |
| `sections` | `AnswerSection[]` |
| `claims` | `Claim[]` |
| `fragments` | `AnswerFragment[]`; фрагменты, на которые ссылаются claims данного ответа |
| `sources` | `AnswerSource[]`; источники этих фрагментов, собранные backend из Evidence |
| `limitations` | `string[]`; пробелы, ограничения и исключённые части смешанного вопроса |
| `clarification` | `AnswerClarification | null` |
| `follow_ups` | `string[]`; предложения продолжения, не автоматически запускаемые действия |
| `style` | `{detail: brief|detailed, level: beginner|advanced}` |

`AnswerSection`: `section_id: string`, `heading: string|null`, `text: string`,
`claim_ids: string[]`.
`Claim`: `claim_id: string`, `statement: string`,
`status: supported|disputed|uncertain`, `fragment_ids: string[]`.
Claim.statement должен воспроизводить утверждение из direct_answer или sections;
UI связывает утверждение с источниками через fragment_ids. Для supported список
непустой. Для disputed нужны фрагменты разных версий, а не только одна ссылка.
Каждое существенное проверяемое утверждение, включая прямой ответ, имеет Claim.
Наличие ссылки не доказывает семантическую поддержку — нужна экспертная оценка.

`AnswerFragment`: `fragment_id: string`, `source_id: string`, `text: string`,
`locator: string|null`. Это публичная проекция Fragment из Evidence без внутренних
ссылок на подвопросы. Текст должен быть допустим к показу по ограничениям источника;
если фрагмент нельзя передавать в UI, он не используется как опора публичного Claim.

`AnswerSource`: `source_id: string`, `url: HTTPS/HTTP URL`, `title: string`,
`author_or_organization: string|null`, `published_date: string|null`,
`retrieved_at: UTC datetime`, `source_type: primary|secondary|encyclopedia|other`,
`access_mode: full_text|excerpt|snippet`, `usage_constraints: string[]`.
Это Source без технического provider_id и внутреннего origin_group.
`AnswerClarification`: `id: string`, `question: string`, `options: string[]`;
внутренние ambiguity_ids остаются в QueryAnalysis.

Ответ самодостаточен для отображения цепочки **утверждение → фрагмент → источник**:

- Каждый Claim.fragment_ids разрешается в Answer.fragments.
- Каждый AnswerFragment.source_id разрешается в Answer.sources с названием и URL.
- Каждый AnswerSection.claim_ids разрешается в Answer.claims; ID уникальны
  внутри соответствующей коллекции. Неиспользуемые фрагменты и источники не включаются.
- При reuse фрагменты и источники копируются в новый Answer с исходным временем
  получения. UI не нужен доступ к предыдущему ответу или внутренней Evidence.
- Backend проверяет соответствие текста и URL полученным Evidence той же сессии.
  URL не берутся из непроверенного текста генератора. UI показывает исходный
  фрагмент и ссылку, не выполняя дополнительный запрос к внутреннему хранилищу.

Для `uncertain` допустим пустой fragment_ids, но отсутствие подтверждения явно
обозначается; UI не рисует фиктивную цепочку цитирования. Ответы-уточнения, отказы
и сообщения о нехватке данных могут иметь пустые claims/fragments/sources.

При `kind=clarification` clarification непустое и completeness=not_applicable;
для других видов clarification=null. Для out_of_scope completeness=not_applicable,
для insufficient_evidence completeness=limited. При частичном поиске, ограниченном
покрытии или смешанном вопросе обязательны completeness=limited и limitations.
Пустая доказательная база не допускает содержательного ответа как подтверждённого.
Уточнения и отказы могут обходиться без источников и вызова генератора.
Техническая ошибка — статус failed с отдельным безопасным объектом ошибки выполнения,
а не выдуманный Answer. Не прошедший валидацию черновик пользователю не показывается.

Пользовательская оценка хранится отдельно от сгенерированного Answer и связывается
с ним по answer_id в авторизованной сессии. Модель не назначает себе оценку.
Показ ответа и отзывы не меняют его содержимое; UI восстанавливает состояние оценки
из API вместе с диалогом. Правила positive/negative/no_feedback, комментария и
агрегации описаны в [жизненном цикле](session-lifecycle.md#учёт-оценок-и-отсутствия-отклика).
Контракт отправки/изменения оценки и отметки показа реализуется отдельными операциями,
не изменением полей четырёх предметных контрактов.

## Ошибки и получение результата

Отправка принятого сообщения возвращает HTTP 202 и `ExecutionAccepted`:
`session_id: UUID`, `request_id: UUID`, `execution_id: UUID`,
`session_status: in_progress`. Статус описывает момент принятия, не гарантирует,
что обработка ещё выполняется при получении HTTP-ответа.

Ошибки API имеют конверт `ApiError`:
`schema_version: "1.0"`, `code: string`, `message: string`,
`session_id: UUID|null`, `request_id: UUID|null`,
`session_status: ready|in_progress|awaiting_clarification|closed|null`,
`active_execution_id: UUID|null`. code выбирается из документированных кодов
маршрута, message не содержит токенов, промптов или сырых ошибок провайдера.
`session_busy` (409) требует in_progress и непустой active_execution_id;
`request_id_conflict` (409) отражает актуальный статус авторизованной сессии.
При отсутствии права доступа поля состояния/ID чужой сессии не раскрываются.

`ExecutionResult`: `schema_version: "1.0"`, `session_id: UUID`, `request_id: UUID`,
`execution_id: UUID`, `status: queued|analyzing|searching|building_evidence|generating|validating|completed|failed|cancelled`,
`answer: Answer|null`, `error: ExecutionError|null`.
`ExecutionError`: `code: provider_error|deadline_exceeded|invalid_output|internal_error`,
`message: string`, `retryable: bool` (возможность новой явной попытки, не команда
автоматически оплачивать повтор). Для completed answer непустой, error=null;
для failed answer=null, error непустой; для остальных статусов оба поля null.
Очистка/TTL удаляют выполнение вместе с сессией; cancelled доступен лишь пока
соответствующее состояние ещё существует, после удаления результат не восстанавливается.

## Сквозной пример связей и проверки при реализации

«Когда сделан и впервые опубликован этот снимок?» при известном произведении:
QueryAnalysis создаёт `q1` о создании и `q2` о первой публикации. SearchPlan содержит
раздельные шаги. Evidence связывает `f1` с `q1`, `f2` с `q2`. Answer содержит два
утверждения с соответствующими фрагментами. Дата публикации страницы источника
не подменяет ни одну из этих исторических дат.

Если источник для `q2` не найден: coverage[q2]=missing, gaps содержит no_results,
Answer.completeness=limited; в тексте нет придуманной даты. Если произведение
неизвестно, выполнение заканчивается уточнением до построения SearchPlan.

Сериализованные примеры четырёх корневых объектов, всех видов Answer и ошибки
занятой сессии: [contract-examples.json](contract-examples.json). Материалы источников
в примере синтетические, не являются реальными результатами поиска.

При реализации проверять отрицательные сценарии: неизвестный tool_id, цикл плана,
несуществующий fragment_id, придуманный URL, snippet под видом full_text,
повтор request_id с другим вводом, доступ к execution_id другой сессии,
устаревшая версия контекста и очистка во время генерации. Положительный сценарий:
одинаковый request_id в двух разных сессиях создаёт независимые выполнения.
Формальные Pydantic/JSON Schema с описаниями и примерами полей и проверки OpenAPI
относятся к реализации этих утверждённых архитектурных контрактов.
