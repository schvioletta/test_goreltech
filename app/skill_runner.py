"""Запуск скилов через LLM: классификатор по description и генерация протокола со строгой проверкой формата."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.llm import ChatModel, LLMError
from app.protocol_parser import TITLE_PREFIX, ProtocolParseError, parse_protocol
from app.registry import Skill

# По условию задания классификатор видит description, обрезанный примерно до 250 символов.
CLASSIFIER_DESCRIPTION_LIMIT = 250
NO_SKILL = "none"
MAX_GENERATION_ATTEMPTS = 2

QUICK_SUMMARY_RE = re.compile(
    r"\b(кратко|коротко|выжимк\w*|tl;?dr)\b|в двух словах|самое главное|short summary",
    re.IGNORECASE,
)

CLASSIFIER_SYSTEM_PROMPT = """Ты — классификатор запросов LLM-ассистента. Ниже список скилов: имя и описание.
Выбери скил, который нужно применить к запросу пользователя, или "{none}", если ни один не подходит.
Выбирай скил только если запрос явно соответствует его описанию; при сомнении отвечай "{none}".

Скилы:
{skills}

Ответь строго JSON-объектом без пояснений: {{"skill": "<имя скила или {none}>"}}"""

REPAIR_PROMPT = """Ответ не прошёл автоматическую проверку формата протокола:
{error}

Выведи протокол целиком заново, исправив ошибку и соблюдая формат из системного промпта. Никакого текста до или после протокола."""


class GenerationFormatError(LLMError):
    """Модель так и не выдала протокол в корректном формате."""

    def __init__(self, message: str, last_output: str, attempts: int) -> None:
        super().__init__(message)
        self.last_output = last_output
        self.attempts = attempts


@dataclass(frozen=True)
class GenerationResult:
    markdown: str
    is_protocol: bool
    attempts: int
    quick_summary: bool


def wants_quick_summary(text: str) -> bool:
    return bool(QUICK_SUMMARY_RE.search(text))


def _read_optional(skill: Skill, rel_path: str) -> str | None:
    path = skill.path / rel_path
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def build_system_prompt(skill: Skill, *, quick_summary: bool) -> str:
    parts = [skill.body]
    reference = _read_optional(skill, "references/protocol_format.md")
    if reference:
        parts.append("# Справочный материал: references/protocol_format.md\n\n" + reference)
    if quick_summary:
        route = _read_optional(skill, "routes/quick_summary.md")
        if route:
            parts.append(
                "# Активный сценарий: routes/quick_summary.md\n\n"
                "Пользователь просит краткость — сценарий ниже обязателен.\n\n" + route
            )
    return "\n\n---\n\n".join(parts)


def generate_protocol(notes: str, skill: Skill, llm: ChatModel) -> GenerationResult:
    """Генерирует протокол по заметкам; при нарушении формата даёт модели исправиться, передав ошибку парсера."""
    quick = wants_quick_summary(notes)
    messages = [
        {"role": "system", "content": build_system_prompt(skill, quick_summary=quick)},
        {"role": "user", "content": notes},
    ]
    last_output, last_error = "", ""
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        output = llm.chat(messages, temperature=0.2).strip()
        if TITLE_PREFIX not in output:
            # По промпту скила ответ без протокола — уточняющий вопрос (например, заметок нет).
            return GenerationResult(markdown=output, is_protocol=False, attempts=attempt, quick_summary=quick)
        if not output.startswith(TITLE_PREFIX):
            last_error = f"первая строка должна начинаться с '{TITLE_PREFIX}', без текста и обёртки в блок кода до неё"
        else:
            try:
                protocol = parse_protocol(output)
            except ProtocolParseError as exc:
                last_error = str(exc)
            else:
                if quick and protocol.summary is None:
                    last_error = "пользователь просил кратко: в конце нужен раздел '## Краткое резюме'"
                else:
                    return GenerationResult(markdown=output, is_protocol=True, attempts=attempt, quick_summary=quick)
        last_output = output
        messages += [
            {"role": "assistant", "content": output},
            {"role": "user", "content": REPAIR_PROMPT.format(error=last_error)},
        ]
    raise GenerationFormatError(
        f"модель не выдала корректный протокол за {MAX_GENERATION_ATTEMPTS} попытки: {last_error}",
        last_output=last_output,
        attempts=MAX_GENERATION_ATTEMPTS,
    )


def build_classifier_prompt(skills: list[Skill]) -> str:
    lines = [f"- {s.name}: {s.description[:CLASSIFIER_DESCRIPTION_LIMIT]}" for s in skills]
    return CLASSIFIER_SYSTEM_PROMPT.format(none=NO_SKILL, skills="\n".join(lines) or "(нет скилов)")


def classify(query: str, skills: list[Skill], llm: ChatModel) -> str | None:
    """Возвращает имя выбранного скила или None. Неизвестное имя от модели трактуется как «ни один»."""
    if not skills:
        return None
    raw = llm.chat(
        [
            {"role": "system", "content": build_classifier_prompt(skills)},
            {"role": "user", "content": query},
        ],
        temperature=0.0,
        json_mode=True,
    )
    try:
        choice = json.loads(raw).get("skill")
    except (ValueError, AttributeError) as exc:
        raise LLMError("классификатор вернул не JSON") from exc
    names = {s.name for s in skills}
    return choice if isinstance(choice, str) and choice in names else None
