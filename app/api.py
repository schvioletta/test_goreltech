"""FastAPI-приложение: реестр скилов и экспорт протокола встречи в .docx."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.docx_generator import protocol_to_docx_bytes
from app.protocol_parser import ProtocolParseError
from app.registry import SkillRegistry

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEFAULT_SKILLS_DIR = "skills"


def create_app(skills_dir: str | Path | None = None) -> FastAPI:
    registry = SkillRegistry(Path(skills_dir or os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR)))
    app = FastAPI(title="Skills API", version="1.0.0")
    app.state.registry = registry

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

    @app.post("/protocol/docx")
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
