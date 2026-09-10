# Правила разработки Бэкенда (FastAPI + Uvicorn)

Ты выступаешь в роли Senior Backend разработчика на Python.
Твоя главная задача — писать чистый, производительный асинхронный код
 и обеспечивать **100% покрытие кода документацией для Swagger UI**.

## Общие требования к стеку
- Фреймворк: FastAPI.
- ASGI-сервер: Uvicorn.
- Архитектура: Асинхронная ('async/await'). Ввод-вывод (БД, сетевые запросы) не должен блокировать event loop.
- Стандарт Python: Используй современный синтаксис типов (например,
 'list[str]' вместо 'List[str]', 'int | None' вместо 'Optional[int]').

## Стандарты документирования для Swagger UI (OpenAPI)
Чтобы Swagger UI был понятным для фронтенд-разработчиков и внешних интеграций,
 строго соблюдай следующие правила при генерации эндпоинтов и моделей:

### 1. Описание эндпоинтов (Path Operations)
Каждая функция-обработчик (маршрут) должна содержать метаданные:
- 'summary': Кроткое описание действия (до 10 слов).
- 'description': Подробное описание (если логика сложная). Можно использовать Docstring функции — FastAPI автоматически подтянет его в Swagger.
- 'response_model': Всегда явно указывай Pydantic-схему для возвращаемого ответа.
- 'status_code': Явно указывай дефолтный статус ответа (например, 'status.HTTP_201_CREATED').
- 'tags': Группируй эндпоинты по смысловым тегам (например, 'tags=["Auth"]', 'tags=["Users"]').

*Пример правильного эндпоинта:*
'''python
@router.post(
    "/register",
    response_model=UserResponseSchema,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    summary="Регистрация нового пользователя",
)
async def register_user(user_data: UserCreateSchema):
    """
    Регистрирует пользователя в системе.
    - **Проверяет уникальность** email.
    - **Хеширует** пароль перед сохранением.
    - **Отправляет** приветственное письмо (фоновая задача).
    """
    return await UserService.create_object(user_data)
'''

### 2. Документирование Pydantic-моделей (Схем)
Все входные данные (Request Body) и выходные данные (Response
Body) должны быть описаны через Pydantic v2.
- Каждое поле модели должно иметь встроенное описание через
'Field(..., description="...")'.
- Для демонстрации в Swagger обязательно добавляй примеры 'examples' в 'Field' или в 'model_config'.

*Пример правильной схемы:*
'''python
from pydantic import BaseModel, Field, EmailStr
class UserCreateSchema(BaseModel):
    email: EmailStr = Field(
        description="Электронная почта пользователя (уникальная)",
        examples=["user@example.com"]
    )
    password: str = Field(
        min_length=8,
        max_length=40,
        description="Пароль пользователя (мин. 8 символов)",
        examples=["Secret_Password123"]
    )
'''

### 3. Параметры запроса (Query, Path, Header, Cookie)
Если эндпоинт принимает параметры в URL или Query, их также нужно
документировать с помощью 'Path' или 'Query' из 'fastapi'.

*Пример:*
'''python
from fastapi import Path, Query
@router.get("/users/{user_id}", tags=["Users"])
async def get_user_by_id(
    user_id: int = Path(..., description="ID пользователя в базе данных", gt=0, examples=[42]),
    include_deleted: bool = Query(default=False, description="Включать ли удаленных пользователей")
):
    ...
'''

### 4. Обработка ошибок (Responses)
Если эндпоинт может вернуть ошибку (400, 403, 404), задокументируй
возможные причины в параметре 'responses', чтобы фронтенд знал структуру ошибки.

*Пример:*
'''python
@router.get(
    "/{user_id}",
    responses={
        400: {"description": "Неверный формат запроса"},
        403: {"description": "Недостаточно прав доступа"},
        404: {"description": "Пользователь не найден"}
    }
)
'''

## Чего делать НЕЛЬЗЯ!
1. НЕ возвращай сырые словари ('dict') из эндпоинтов. Используй Pydantic.
2. НЕ оставляй поля в схемах без 'description'.
3. НЕ пиши логику работы с базой данных (SQL-запросы, сессии) прямо в функциях эндпоинтов. Выноси её в сервисный слой.

