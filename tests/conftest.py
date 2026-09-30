from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

VALID_PROTOCOL = """# Протокол встречи: Планирование релиза

## Метаданные

- Дата: 14.10.2025
- Время: 11:00-12:00
- Место: Zoom
- Участники: Анна Смирнова (PM), Игорь Петров (QA)

## Обсуждение

### Дата релиза

Рассматривалась дата 10.11.

Зафиксирована дата 12.11.

### Аналитика

Обсуждался переход на Amplitude.

## Решения

1. Перенести релиз на 12.11.2025.
2. Включить пуш-уведомления в релиз.

## Задачи

| Задача | Ответственный | Срок |
| --- | --- | --- |
| Подготовить план регресса | Игорь Петров | 31.10.2025 |
| Обновить release notes | не указан | не указан |

## Риски и открытые вопросы

- Не назначен ответственный: обновить release notes.
"""

EMPTY_PROTOCOL = """# Протокол встречи: не указано

## Метаданные

- Дата: не указано
- Время: не указано
- Место: не указано
- Участники: не указано

## Обсуждение

— не указано —

## Решения

— не указано —

## Задачи

— не указано —

## Риски и открытые вопросы

— не указано —
"""


@pytest.fixture
def valid_protocol() -> str:
    return VALID_PROTOCOL


@pytest.fixture
def empty_protocol() -> str:
    return EMPTY_PROTOCOL


def write_skill(root: Path, dirname: str, content: str | None, extra_files: dict[str, str] | None = None) -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    if content is not None:
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    for rel, text in (extra_files or {}).items():
        path = skill_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return skill_dir


def skill_md(name: str | None = "demo-skill", description: str | None = "Когда применять.",
             caption: str | None = "Демо", body: str = "Тело промпта.") -> str:
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if caption is not None:
        lines.append(f"caption: {caption}")
    if description is not None:
        lines.append(f"description: {description}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body + "\n"
