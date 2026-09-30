"""Строгий парсер протокола встречи.

Формат описан в skills/meeting-protocol/references/protocol_format.md. Любое отклонение
от контракта — ProtocolParseError с номером строки; парсер ничего не угадывает.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TITLE_PREFIX = "# Протокол встречи: "

SECTION_METADATA = "Метаданные"
SECTION_DISCUSSION = "Обсуждение"
SECTION_DECISIONS = "Решения"
SECTION_TASKS = "Задачи"
SECTION_RISKS = "Риски и открытые вопросы"
SECTION_SUMMARY = "Краткое резюме"

REQUIRED_SECTIONS = (
    SECTION_METADATA,
    SECTION_DISCUSSION,
    SECTION_DECISIONS,
    SECTION_TASKS,
    SECTION_RISKS,
)

META_KEYS = ("Дата", "Время", "Место", "Участники")

PLACEHOLDER_META = "не указано"
PLACEHOLDER_CELL = "не указан"
PLACEHOLDER_EMPTY = "— не указано —"

TASKS_HEADER = "| Задача | Ответственный | Срок |"
TASKS_SEPARATOR = "| --- | --- | --- |"
TASKS_COLUMNS = ("Задача", "Ответственный", "Срок")

H1_RE = re.compile(r"^# Протокол встречи: (.+)$")
H2_RE = re.compile(r"^## (.+)$")
H3_RE = re.compile(r"^### (.+)$")
HEADING_RE = re.compile(r"^#+\s")
META_RE = re.compile(r"^- (" + "|".join(META_KEYS) + r"): (.+)$")
ROW_RE = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \|$")
NUMBERED_RE = re.compile(r"^(\d+)\. (.+)$")
BULLET_RE = re.compile(r"^- (.+)$")
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}(?:-\d{2}:\d{2})?$")


class ProtocolParseError(ValueError):
    def __init__(self, message: str, line_no: int | None = None) -> None:
        self.line_no = line_no
        super().__init__(f"строка {line_no}: {message}" if line_no else message)


@dataclass(frozen=True)
class Task:
    task: str
    owner: str = PLACEHOLDER_CELL
    due: str = PLACEHOLDER_CELL


@dataclass
class Protocol:
    title: str
    metadata: dict[str, str] = field(default_factory=dict)
    discussion: list[tuple[str, str]] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    summary: list[str] | None = None


Line = tuple[int, str]


def _content_lines(text: str) -> list[Line]:
    """Нормализует переводы строк и хвостовые пробелы, отбрасывает пустые строки, сохраняя номера."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return [(no, line.rstrip()) for no, line in enumerate(text.split("\n"), start=1) if line.strip()]


def _is_empty_marker(lines: list[Line]) -> bool:
    return len(lines) == 1 and lines[0][1] == PLACEHOLDER_EMPTY


def _reject_stray_empty_marker(lines: list[Line]) -> None:
    for no, line in lines:
        if line == PLACEHOLDER_EMPTY:
            raise ProtocolParseError(f"'{PLACEHOLDER_EMPTY}' должна быть единственной строкой раздела", no)


def _parse_metadata(lines: list[Line], header_no: int) -> dict[str, str]:
    if not lines:
        raise ProtocolParseError("раздел метаданных пуст", header_no)
    metadata: dict[str, str] = {}
    last_index = -1
    for no, line in lines:
        m = META_RE.match(line)
        if not m:
            raise ProtocolParseError(f"ожидалась строка вида '- Ключ: значение' с ключом из {META_KEYS}", no)
        key, value = m.group(1), m.group(2).strip()
        index = META_KEYS.index(key)
        if key in metadata:
            raise ProtocolParseError(f"ключ метаданных '{key}' повторяется", no)
        if index < last_index:
            raise ProtocolParseError(f"нарушен порядок ключей метаданных, ожидается {META_KEYS}", no)
        last_index = index
        if key == "Дата" and value != PLACEHOLDER_META and not DATE_RE.match(value):
            raise ProtocolParseError(f"дата должна быть ДД.ММ.ГГГГ или '{PLACEHOLDER_META}'", no)
        if key == "Время" and value != PLACEHOLDER_META and not TIME_RE.match(value):
            raise ProtocolParseError(f"время должно быть ЧЧ:ММ, ЧЧ:ММ-ЧЧ:ММ или '{PLACEHOLDER_META}'", no)
        metadata[key] = value
    missing = [k for k in META_KEYS if k not in metadata]
    if missing:
        raise ProtocolParseError(f"нет обязательных ключей метаданных: {', '.join(missing)}", header_no)
    return metadata


def _parse_discussion(lines: list[Line]) -> list[tuple[str, str]]:
    if _is_empty_marker(lines):
        return []
    _reject_stray_empty_marker(lines)
    topics: list[tuple[str, list[str], int]] = []
    for no, line in lines:
        m = H3_RE.match(line)
        if m:
            topics.append((m.group(1).strip(), [], no))
            continue
        if HEADING_RE.match(line):
            raise ProtocolParseError("в разделе 'Обсуждение' допустимы только заголовки '### '", no)
        if line.startswith("|"):
            raise ProtocolParseError("таблицы допустимы только в разделе 'Задачи'", no)
        if BULLET_RE.match(line) or NUMBERED_RE.match(line):
            raise ProtocolParseError("в разделе 'Обсуждение' под темой допустимы только абзацы, без списков", no)
        if not topics:
            raise ProtocolParseError("текст обсуждения должен идти под заголовком '### <тема>'", no)
        topics[-1][1].append(line.strip())
    result = []
    for topic, body, no in topics:
        if not body:
            raise ProtocolParseError(f"у темы '{topic}' нет содержания", no)
        result.append((topic, "\n".join(body)))
    return result


def _parse_numbered(lines: list[Line]) -> list[str]:
    if _is_empty_marker(lines):
        return []
    items = []
    for expected, (no, line) in enumerate(lines, start=1):
        m = NUMBERED_RE.match(line)
        if not m:
            raise ProtocolParseError("ожидался пункт нумерованного списка 'N. текст'", no)
        if int(m.group(1)) != expected:
            raise ProtocolParseError(f"нарушена нумерация: ожидался номер {expected}", no)
        items.append(m.group(2).strip())
    return items


def _parse_bullets(lines: list[Line], section: str) -> list[str]:
    if _is_empty_marker(lines):
        return []
    _reject_stray_empty_marker(lines)
    items = []
    for no, line in lines:
        m = BULLET_RE.match(line)
        if not m:
            raise ProtocolParseError(f"в разделе '{section}' допустим только список '- '", no)
        items.append(m.group(1).strip())
    return items


def _parse_tasks(lines: list[Line], header_no: int) -> list[Task]:
    if _is_empty_marker(lines):
        return []
    if len(lines) < 3:
        raise ProtocolParseError("таблица задач должна содержать шапку, разделитель и хотя бы одну строку", header_no)
    (h_no, header), (s_no, separator) = lines[0], lines[1]
    if header != TASKS_HEADER:
        raise ProtocolParseError(f"шапка таблицы задач должна быть '{TASKS_HEADER}'", h_no)
    if separator != TASKS_SEPARATOR:
        raise ProtocolParseError(f"разделитель таблицы задач должен быть '{TASKS_SEPARATOR}'", s_no)
    tasks = []
    for no, line in lines[2:]:
        m = ROW_RE.match(line)
        if not m:
            raise ProtocolParseError("строка таблицы задач должна содержать ровно 3 ячейки", no)
        task, owner, due = (cell.strip() for cell in m.groups())
        if not task or not owner or not due:
            raise ProtocolParseError("ячейки таблицы задач не могут быть пустыми", no)
        if due != PLACEHOLDER_CELL and not DATE_RE.match(due):
            raise ProtocolParseError(f"срок должен быть ДД.ММ.ГГГГ или '{PLACEHOLDER_CELL}'", no)
        tasks.append(Task(task=task, owner=owner, due=due))
    return tasks


def _split_sections(lines: list[Line]) -> list[tuple[str, int, list[Line]]]:
    sections: list[tuple[str, int, list[Line]]] = []
    for no, line in lines:
        m = H2_RE.match(line)
        if m:
            sections.append((m.group(1).strip(), no, []))
            continue
        if not sections:
            raise ProtocolParseError("после заголовка H1 ожидается '## Метаданные'", no)
        sections[-1][2].append((no, line))
    return sections


def validate_protocol(text: str) -> list[str]:
    """Возвращает список обязательных H2-разделов, которых нет в документе."""
    present = {m.group(1).strip() for _, line in _content_lines(text) if (m := H2_RE.match(line))}
    return [name for name in REQUIRED_SECTIONS if name not in present]


def parse_protocol(text: str) -> Protocol:
    lines = _content_lines(text)
    if not lines:
        raise ProtocolParseError("документ пуст")

    first_no, first = lines[0]
    m = H1_RE.match(first)
    if not m:
        raise ProtocolParseError(f"первая строка должна начинаться с '{TITLE_PREFIX}'", first_no)
    title = m.group(1).strip()

    sections = _split_sections(lines[1:])
    names = [name for name, _, _ in sections]
    if names not in (list(REQUIRED_SECTIONS), [*REQUIRED_SECTIONS, SECTION_SUMMARY]):
        missing = validate_protocol(text)
        detail = f"отсутствуют разделы: {', '.join(missing)}" if missing else f"получено: {names}"
        raise ProtocolParseError(
            f"разделы H2 должны идти строго в порядке {list(REQUIRED_SECTIONS)} "
            f"(+ опционально '{SECTION_SUMMARY}' в конце); {detail}"
        )

    protocol = Protocol(title=title)
    for name, header_no, body in sections:
        if not body and name != SECTION_METADATA:
            raise ProtocolParseError(
                f"раздел '{name}' пуст; для пустого раздела нужна строка '{PLACEHOLDER_EMPTY}'", header_no
            )
        if name != SECTION_DISCUSSION:
            for no, line in body:
                if HEADING_RE.match(line):
                    raise ProtocolParseError("заголовки H3 допустимы только в разделе 'Обсуждение'", no)
        if name == SECTION_METADATA:
            protocol.metadata = _parse_metadata(body, header_no)
        elif name == SECTION_DISCUSSION:
            protocol.discussion = _parse_discussion(body)
        elif name == SECTION_DECISIONS:
            protocol.decisions = _parse_numbered(body)
        elif name == SECTION_TASKS:
            protocol.tasks = _parse_tasks(body, header_no)
        elif name == SECTION_RISKS:
            protocol.risks = _parse_bullets(body, name)
        elif name == SECTION_SUMMARY:
            protocol.summary = _parse_bullets(body, name)
    return protocol
