"""Реестр скилов: загрузка каталогов со SKILL.md, валидация, поиск и потокобезопасная перезагрузка."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SKILL_FILE = "SKILL.md"
NAME_MAX_LEN = 64
DESCRIPTION_MAX_LEN = 1024
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_OPEN = "---"
FRONTMATTER_CLOSE = ("---", "...")


class SkillValidationError(ValueError):
    """Скил не прошёл валидацию. Наружу из реестра не выходит — превращается в warning."""


@dataclass(frozen=True)
class Skill:
    name: str
    caption: str
    description: str
    body: str
    path: Path
    has_files: bool

    def to_meta(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "caption": self.caption,
            "description": self.description,
            "has_files": self.has_files,
        }


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Отделяет YAML-frontmatter от тела.

    Frontmatter есть, только если первая строка файла — «---»; закрывается строкой «---» или «...».
    Без открывающего разделителя весь файл считается телом, метаданные пусты.
    """
    text = text.lstrip("﻿").replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_OPEN:
        return {}, text

    for idx in range(1, len(lines)):
        if lines[idx].strip() in FRONTMATTER_CLOSE:
            raw_meta = "\n".join(lines[1:idx])
            body = "\n".join(lines[idx + 1 :])
            break
    else:
        raise SkillValidationError("frontmatter не закрыт строкой '---'")

    try:
        meta = yaml.safe_load(raw_meta) if raw_meta.strip() else {}
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"некорректный YAML во frontmatter: {exc}") from exc
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise SkillValidationError("frontmatter должен быть YAML-словарём")
    return meta, body


def _optional_str(meta: dict[str, Any], key: str) -> str | None:
    value = meta.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SkillValidationError(f"поле '{key}' должно быть строкой")
    return value.strip()


def _has_extra_files(skill_dir: Path) -> bool:
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_dir)
        if rel == Path(SKILL_FILE) or any(part.startswith(".") for part in rel.parts):
            continue
        return True
    return False


def load_skill(skill_dir: Path) -> Skill:
    """Загружает и валидирует один скил. При любой ошибке бросает SkillValidationError."""
    skill_file = skill_dir / SKILL_FILE
    if not skill_file.is_file():
        raise SkillValidationError(f"нет файла {SKILL_FILE}")
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillValidationError(f"не удалось прочитать {SKILL_FILE}: {exc}") from exc

    meta, body = split_frontmatter(text)

    name = _optional_str(meta, "name") or skill_dir.name
    if len(name) > NAME_MAX_LEN:
        raise SkillValidationError(f"name длиннее {NAME_MAX_LEN} символов")
    if not NAME_RE.match(name):
        raise SkillValidationError(f"name '{name}' не в формате kebab-case")

    description = _optional_str(meta, "description")
    if not description:
        raise SkillValidationError("description обязательна")
    if len(description) > DESCRIPTION_MAX_LEN:
        raise SkillValidationError(
            f"description длиннее {DESCRIPTION_MAX_LEN} символов ({len(description)})"
        )

    body = body.strip()
    if not body:
        raise SkillValidationError("тело SKILL.md пустое")

    caption = _optional_str(meta, "caption") or name

    return Skill(
        name=name,
        caption=caption,
        description=description,
        body=body,
        path=skill_dir,
        has_files=_has_extra_files(skill_dir),
    )


class SkillRegistry:
    """Потокобезопасный реестр скилов.

    Читатели берут ссылку на текущий словарь под RLock и дальше работают со снимком.
    reload() собирает новый словарь без блокировки и атомарно подменяет ссылку под RLock,
    поэтому чтение во время перезагрузки видит либо старый, либо новый набор целиком.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self._skills: dict[str, Skill] = {}
        self.reload()

    def _snapshot(self) -> dict[str, Skill]:
        with self._lock:
            return self._skills

    def _scan(self) -> dict[str, Skill]:
        skills: dict[str, Skill] = {}
        if not self.root.is_dir():
            logger.warning("Каталог скилов не найден: %s", self.root)
            return skills

        for skill_dir in sorted(self.root.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith((".", "_")):
                continue
            try:
                skill = load_skill(skill_dir)
            except SkillValidationError as exc:
                logger.warning("Скил %s пропущен: %s", skill_dir, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — битый скил не должен ронять реестр
                logger.warning("Скил %s пропущен из-за непредвиденной ошибки: %r", skill_dir, exc)
                continue
            if skill.name in skills:
                logger.warning(
                    "Скил %s пропущен: имя '%s' уже занято скилом %s",
                    skill_dir,
                    skill.name,
                    skills[skill.name].path,
                )
                continue
            skills[skill.name] = skill
        return skills

    def reload(self) -> int:
        """Пересобирает реестр и возвращает число загруженных скилов."""
        new_skills = self._scan()
        with self._lock:
            self._skills = new_skills
        logger.info("Реестр скилов загружен: %d шт. из %s", len(new_skills), self.root)
        return len(new_skills)

    def list(self, q: str | None = None) -> list[Skill]:
        skills = sorted(self._snapshot().values(), key=lambda s: s.name)
        if not q or not q.strip():
            return skills
        needle = q.strip().casefold()
        return [s for s in skills if needle in s.name.casefold() or needle in s.caption.casefold()]

    def get(self, name: str) -> Skill | None:
        return self._snapshot().get(name)

    def __len__(self) -> int:
        return len(self._snapshot())
