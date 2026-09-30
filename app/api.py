"""FastAPI-приложение: реестр скилов и экспорт протокола встречи в .docx."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.docx_generator import protocol_to_docx_bytes
from app.protocol_parser import ProtocolParseError
from app.registry import SkillRegistry

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEFAULT_SKILLS_DIR = "skills"
INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"

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


def create_app(skills_dir: str | Path | None = None) -> FastAPI:
    registry = SkillRegistry(Path(skills_dir or os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR)))
    app = FastAPI(
        title="Skills API",
        version="1.0.0",
        description="Реестр скилов и экспорт протокола встречи в Word. Веб-интерфейс — на [главной странице](/).",
    )
    app.state.registry = registry

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")

    @app.get("/skills")
    def list_skills(q: str | None = None) -> list[dict[str, Any]]:
        return [skill.to_meta() for skill in registry.list(q)]

    @app.get("/skills/{name}")
    def get_skill(name: str) -> dict[str, Any]:
        skill = registry.get(name)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Скил '{name}' не найден")
        return {**skill.to_meta(), "body": skill.body}

    @app.post("/skills/reload")
    def reload_skills() -> dict[str, Any]:
        return {"status": "ok", "count": registry.reload()}

    @app.post(
        "/protocol/docx",
        openapi_extra=PROTOCOL_DOCX_OPENAPI,
        responses=PROTOCOL_DOCX_RESPONSES,
        response_class=Response,
    )
    async def protocol_docx(request: Request) -> Response:
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="Тело запроса должно быть JSON: {\"markdown\": \"...\"}")
        markdown = payload.get("markdown") if isinstance(payload, dict) else None
        if not isinstance(markdown, str) or not markdown.strip():
            raise HTTPException(status_code=400, detail="Поле 'markdown' обязательно и не может быть пустым")

        try:
            content = await run_in_threadpool(protocol_to_docx_bytes, markdown)
        except ProtocolParseError as exc:
            raise HTTPException(status_code=422, detail=f"Протокол не соответствует формату: {exc}")

        return Response(
            content=content,
            media_type=DOCX_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="protocol.docx"'},
        )

    return app


app = create_app()
