"""FastAPI-приложение: реестр скилов, генерация протокола через LLM и экспорт в .docx."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.docx_generator import protocol_to_docx_bytes
from app.evals import SKILL_UNDER_TEST, load_eval_queries, load_example_notes
from app.llm import ChatModel, DeepSeekClient, LLMError, load_env_file
from app.protocol_parser import ProtocolParseError
from app.rate_limit import SlidingWindowLimiter
from app.registry import SkillRegistry
from app.skill_runner import GenerationFormatError, classify, generate_protocol

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEFAULT_SKILLS_DIR = "skills"
INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"
MAX_NOTES_CHARS = 20_000
MAX_QUERY_CHARS = 2_000
_FROM_ENV: Any = object()

SWAGGER_EXAMPLE_MARKDOWN = """# Протокол встречи: Планирование релиза

## Метаданные

- Дата: 14.10.2025
- Время: 11:00-12:00
- Место: Zoom
- Участники: Анна Смирнова (PM), Игорь Петров (QA)

## Обсуждение

### Дата релиза

Обсуждали перенос релиза из-за регрессионного тестирования.

## Решения

1. Перенести релиз на 12.11.2025.

## Задачи

| Задача | Ответственный | Срок |
| --- | --- | --- |
| Подготовить план регресса | Игорь Петров | 31.10.2025 |
| Обновить release notes | не указан | не указан |

## Риски и открытые вопросы

- Не назначен ответственный: обновить release notes.
"""

# Тело разбирается вручную (ТЗ требует 400, а не 422 на пустой markdown),
# поэтому схему запроса и ответа описываем для Swagger явно.
PROTOCOL_DOCX_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["markdown"],
                    "properties": {
                        "markdown": {
                            "type": "string",
                            "description": "Протокол встречи в формате скила meeting-protocol",
                        }
                    },
                },
                "example": {"markdown": SWAGGER_EXAMPLE_MARKDOWN},
            }
        },
    }
}
PROTOCOL_DOCX_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Документ Word",
        "content": {DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    },
    400: {"description": "Нет поля markdown, оно пустое или тело — не JSON"},
    422: {"description": "Markdown не соответствует формату протокола (в detail — номер строки)"},
}


def _json_body_openapi(field: str, description: str, example: str) -> dict[str, Any]:
    # Тела разбираются вручную (400 на пустое поле), поэтому схему для Swagger описываем явно.
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": [field],
                        "properties": {field: {"type": "string", "description": description}},
                    },
                    "example": {field: example},
                }
            },
        }
    }


LLM_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Поле отсутствует, пустое, слишком длинное или тело — не JSON"},
    429: {"description": "Превышен лимит запросов к LLM"},
    502: {"description": "Ошибка при обращении к LLM"},
    503: {"description": "LLM не настроена: не задан DEEPSEEK_API_KEY"},
}


async def read_text_field(request: Request, field: str, max_len: int | None = None) -> str:
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail=f'Тело запроса должно быть JSON: {{"{field}": "..."}}')
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"Поле '{field}' обязательно и не может быть пустым")
    if max_len is not None and len(value) > max_len:
        raise HTTPException(status_code=400, detail=f"Поле '{field}' длиннее {max_len} символов")
    return value


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


SkillQuery = Annotated[
    str | None,
    Query(
        description="Подстрока для поиска по `name` и `caption` без учёта регистра. Пусто — вернуть все скилы.",
        openapi_examples={
            "caption": {"summary": "Поиск по caption: «протокол»", "value": "протокол"},
            "name": {"summary": "Поиск по name: «meet»", "value": "meet"},
            "nothing": {"summary": "Ничего не найдено: «nope»", "value": "nope"},
        },
    ),
]
SkillName = Annotated[
    str,
    PathParam(
        description="Имя скила (`name` из SKILL.md, kebab-case). Список имён — в `GET /skills`.",
        openapi_examples={
            "found": {"summary": "Существующий скил", "value": "meeting-protocol"},
            "not_found": {"summary": "Несуществующий скил → 404", "value": "nope"},
        },
    ),
]


def create_app(
    skills_dir: str | Path | None = None,
    llm: ChatModel | None = _FROM_ENV,
    per_ip_limiter: SlidingWindowLimiter | None = None,
    global_limiter: SlidingWindowLimiter | None = None,
) -> FastAPI:
    load_env_file()
    registry = SkillRegistry(Path(skills_dir or os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR)))
    if llm is _FROM_ENV:
        llm = DeepSeekClient.from_env()
    per_ip_limiter = per_ip_limiter or SlidingWindowLimiter(int(os.getenv("LLM_RATE_PER_MINUTE", "20")), 60)
    global_limiter = global_limiter or SlidingWindowLimiter(int(os.getenv("LLM_DAILY_LIMIT", "300")), 86_400)

    app = FastAPI(
        title="Skills API",
        version="1.1.0",
        description=(
            "Реестр скилов, генерация протокола встречи через LLM (DeepSeek) и экспорт в Word. "
            "Веб-интерфейс — на [главной странице](/)."
        ),
    )
    app.state.registry = registry
    app.state.llm = llm

    def require_llm(request: Request) -> ChatModel:
        if llm is None:
            raise HTTPException(status_code=503, detail="LLM не настроена: задайте переменную окружения DEEPSEEK_API_KEY")
        if not per_ip_limiter.allow(_client_ip(request)) or not global_limiter.allow("global"):
            raise HTTPException(status_code=429, detail="Слишком много запросов к LLM, попробуйте позже")
        return llm

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")

    @app.get("/skills", summary="Список скилов (с поиском)")
    def list_skills(q: SkillQuery = None) -> list[dict[str, Any]]:
        return [skill.to_meta() for skill in registry.list(q)]

    @app.get(
        "/skills/{name}",
        summary="Скил по имени: метаданные и системный промпт",
        responses={404: {"description": "Скил с таким именем не найден"}},
    )
    def get_skill(name: SkillName) -> dict[str, Any]:
        skill = registry.get(name)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Скил '{name}' не найден")
        return {**skill.to_meta(), "body": skill.body}

    @app.post("/skills/reload", summary="Перечитать каталог скилов")
    def reload_skills() -> dict[str, Any]:
        return {"status": "ok", "count": registry.reload()}

    @app.post(
        "/protocol/docx",
        summary="Протокол встречи (markdown) → документ Word",
        openapi_extra=PROTOCOL_DOCX_OPENAPI,
        responses=PROTOCOL_DOCX_RESPONSES,
        response_class=Response,
    )
    async def protocol_docx(request: Request) -> Response:
        markdown = await read_text_field(request, "markdown")
        try:
            content = await run_in_threadpool(protocol_to_docx_bytes, markdown)
        except ProtocolParseError as exc:
            raise HTTPException(status_code=422, detail=f"Протокол не соответствует формату: {exc}")

        return Response(
            content=content,
            media_type=DOCX_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="protocol.docx"'},
        )

    @app.get("/llm/status", summary="Подключена ли LLM")
    def llm_status() -> dict[str, Any]:
        return {"configured": llm is not None, "model": getattr(llm, "model", None)}

    @app.post(
        "/protocol/generate",
        summary="Заметки о встрече → протокол (LLM со скилом meeting-protocol)",
        description=(
            "Тело SKILL.md уходит в LLM системным промптом. Ответ проверяется строгим парсером; "
            "при нарушении формата модель получает текст ошибки и одну попытку исправиться. "
            "Если заметки просят «кратко»/TL;DR, подключается routes/quick_summary.md."
        ),
        openapi_extra=_json_body_openapi("notes", "Неструктурированные заметки о встрече", load_example_notes()),
        responses={**LLM_RESPONSES, 422: {"description": "Модель не выдала корректный протокол за 2 попытки"}},
    )
    async def protocol_generate(request: Request) -> dict[str, Any]:
        notes = await read_text_field(request, "notes", MAX_NOTES_CHARS)
        model = require_llm(request)
        skill = registry.get(SKILL_UNDER_TEST)
        if skill is None:
            raise HTTPException(status_code=503, detail=f"Скил '{SKILL_UNDER_TEST}' не загружен")
        try:
            result = await run_in_threadpool(generate_protocol, notes, skill, model)
        except GenerationFormatError as exc:
            raise HTTPException(
                status_code=422,
                detail={"message": str(exc), "last_output": exc.last_output, "attempts": exc.attempts},
            )
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=f"Ошибка LLM: {exc}")
        return {
            "markdown": result.markdown,
            "is_protocol": result.is_protocol,
            "attempts": result.attempts,
            "quick_summary": result.quick_summary,
            "skill": skill.name,
            "model": model.model,
        }

    @app.post(
        "/skills/classify",
        summary="Классификатор: какой скил выбрать для запроса",
        description="LLM получает description всех скилов, обрезанные до 250 символов, и выбирает скил или «ни один».",
        openapi_extra=_json_body_openapi("query", "Запрос пользователя", "Сделай саммари вчерашнего созвона с клиентом"),
        responses=LLM_RESPONSES,
    )
    async def skills_classify(request: Request) -> dict[str, Any]:
        query = await read_text_field(request, "query", MAX_QUERY_CHARS)
        model = require_llm(request)
        try:
            skill = await run_in_threadpool(classify, query, registry.list(), model)
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=f"Ошибка LLM: {exc}")
        return {"skill": skill, "model": model.model}

    @app.get("/eval/queries", summary="Eval-запросы из eval_queries.md с ожидаемым результатом")
    def eval_queries() -> list[dict[str, Any]]:
        return [q.to_dict() for q in load_eval_queries()]

    return app


app = create_app()
