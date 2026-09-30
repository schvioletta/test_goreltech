import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SAMPLE_PROTOCOL = """# Протокол встречи: Планирование релиза v2.0

## Метаданные

- Дата: 14.10.2025
- Время: 11:00-12:00
- Место: Zoom
- Участники: Анна Смирнова (PM), Дмитрий Ковалёв (backend), Игорь Петров (QA)

## Обсуждение

### Дата релиза

Изначально рассматривалась дата 10.11. Игорь Петров возразил: регрессу не хватает 3 дней.

Анна Смирнова зафиксировала дату 12.11 как окончательную.

### Аналитика

Обсуждался переход на Amplitude вместо Firebase. Решение не принято.

## Решения

1. Перенести релиз v2.0 на 12.11.2025.
2. Включить пуш-уведомления в релиз v2.0.

## Задачи

| Задача | Ответственный | Срок |
| --- | --- | --- |
| Завершить разработку API пуш-уведомлений | Дмитрий Ковалёв | 24.10.2025 |
| Подготовить план регрессионного тестирования | Игорь Петров | 31.10.2025 |
| Обновить release notes для стора | не указан | не указан |

## Риски и открытые вопросы

- Не назначен ответственный: обновить release notes для стора.
- Не принято решение по системе аналитики: Amplitude или Firebase.
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


def _yaml_str(value: str) -> str:
    # JSON-строка — валидный YAML-скаляр в двойных кавычках; PyYAML в тестах не нужен.
    return json.dumps(value, ensure_ascii=False)


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    return root


@pytest.fixture
def make_skill(skills_root: Path):
    """Фабрика скилов в каталоге skills_root.

    name / caption / description = None — поле не попадает во frontmatter.
    frontmatter — сырой YAML между строками «---», заменяет сгенерированный.
    with_skill_md=False — каталог без SKILL.md. files — дополнительные файлы {относительный путь: текст}.
    """

    def _make(
        name: str | None = "demo-skill",
        body: str = "Тело системного промпта.",
        caption: str | None = "Демо-скил",
        description: str | None = "Когда применять демо-скил.",
        frontmatter: str | None = None,
        dirname: str | None = None,
        files: dict[str, str] | None = None,
        with_skill_md: bool = True,
    ) -> Path:
        skill_dir = skills_root / (dirname or name or "skill")
        skill_dir.mkdir(parents=True, exist_ok=True)

        if with_skill_md:
            if frontmatter is None:
                fields = {"name": name, "caption": caption, "description": description}
                frontmatter = "\n".join(f"{k}: {_yaml_str(v)}" for k, v in fields.items() if v is not None)
            (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")

        for rel, text in (files or {}).items():
            path = skill_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return skill_dir

    return _make


@pytest.fixture
def sample_protocol() -> str:
    return SAMPLE_PROTOCOL


@pytest.fixture
def empty_protocol() -> str:
    return EMPTY_PROTOCOL
