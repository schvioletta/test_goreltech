import pytest

from app.protocol_parser import REQUIRED_SECTIONS, ProtocolParseError, Task, parse_protocol, validate_protocol
from tests.conftest import ROOT


def test_parse_valid(sample_protocol):
    p = parse_protocol(sample_protocol)
    assert p.title == "Планирование релиза v2.0"
    assert list(p.metadata) == ["Дата", "Время", "Место", "Участники"]
    assert p.discussion[0] == (
        "Дата релиза",
        "Изначально рассматривалась дата 10.11. Игорь Петров возразил: регрессу не хватает 3 дней.\n"
        "Анна Смирнова зафиксировала дату 12.11 как окончательную.",
    )
    assert p.tasks[-1] == Task("Обновить release notes для стора", "не указан", "не указан")
    assert p.summary is None


def test_parse_empty_sections(empty_protocol):
    p = parse_protocol(empty_protocol)
    assert p.title == "не указано"
    assert set(p.metadata.values()) == {"не указано"}
    assert (p.discussion, p.decisions, p.tasks, p.risks) == ([], [], [], [])


def test_parse_crlf_and_summary(sample_protocol):
    text = sample_protocol + "\n## Краткое резюме\n\n- Релиз 12.11.2025.\n"
    assert parse_protocol(text.replace("\n", "\r\n")).summary == ["Релиз 12.11.2025."]


def test_eval_example_parses():
    text = (ROOT / "eval_queries.md").read_text(encoding="utf-8")
    p = parse_protocol(text.split("### Ожидаемый ответ")[1].split("```")[1])
    assert len(p.tasks) == 5
    assert p.tasks[3] == Task("Обновить release notes для стора", "не указан", "не указан")


def test_validate_reports_missing_sections(sample_protocol):
    assert validate_protocol(sample_protocol) == []
    assert validate_protocol(sample_protocol.replace("## Решения", "## Итоги")) == ["Решения"]
    assert validate_protocol("") == list(REQUIRED_SECTIONS)


TASK_ROW = "| Завершить разработку API пуш-уведомлений | Дмитрий Ковалёв | 24.10.2025 |"
PARTICIPANTS = "- Участники: Анна Смирнова (PM), Дмитрий Ковалёв (backend), Игорь Петров (QA)\n"


@pytest.mark.parametrize(
    "old, new",
    [
        ("# Протокол встречи: Планирование", "# Протокол: Планирование"),
        ("## Решения", "## Итоги"),
        ("| Задача | Ответственный | Срок |", "| Задача | Ответственный | Срок | Статус |"),
        ("| --- | --- | --- |", "|---|---|---|"),
        (TASK_ROW, TASK_ROW.replace("24.10.2025", "скоро")),
        (TASK_ROW, "| Завершить разработку API пуш-уведомлений | Дмитрий Ковалёв |"),
        ("2. Включить", "3. Включить"),
        ("- Не назначен ответственный", "* Не назначен ответственный"),
        ("### Аналитика", "#### Аналитика"),
        ("- Дата: 14.10.2025", "- Дата: 14 октября"),
        ("- Время: 11:00-12:00", "- Время: утром"),
        ("- Место: Zoom\n", ""),
        (PARTICIPANTS, PARTICIPANTS + "- Ведущий: Анна Смирнова\n"),
        ("- Место: Zoom\n" + PARTICIPANTS, PARTICIPANTS + "- Место: Zoom\n"),
        ("Изначально рассматривалась", "- Изначально рассматривалась"),
        ("Изначально рассматривалась", "1. Изначально рассматривалась"),
        ("1. Перенести релиз v2.0 на 12.11.2025.\n2. Включить пуш-уведомления в релиз v2.0.\n", ""),
        ("- Не принято решение", "— не указано —\n- Не принято решение"),
    ],
)
def test_strict_format_violations(sample_protocol, old, new):
    assert old in sample_protocol
    with pytest.raises(ProtocolParseError):
        parse_protocol(sample_protocol.replace(old, new))


def test_wrong_section_order(sample_protocol):
    swapped = sample_protocol.replace("## Решения", "@@").replace("## Задачи", "## Решения").replace("@@", "## Задачи")
    with pytest.raises(ProtocolParseError):
        parse_protocol(swapped)


def test_text_before_title_rejected(sample_protocol):
    with pytest.raises(ProtocolParseError):
        parse_protocol("Вот ваш протокол:\n\n" + sample_protocol)


def test_h3_outside_discussion_rejected(sample_protocol):
    with pytest.raises(ProtocolParseError):
        parse_protocol(sample_protocol.replace("## Решения\n", "## Решения\n\n### Подтема\n"))


def test_discussion_text_without_topic_rejected(sample_protocol):
    with pytest.raises(ProtocolParseError):
        parse_protocol(sample_protocol.replace("## Обсуждение\n", "## Обсуждение\n\nТекст без темы.\n"))


def test_error_contains_line_number(sample_protocol):
    with pytest.raises(ProtocolParseError) as exc_info:
        parse_protocol(sample_protocol.replace("24.10.2025", "скоро"))
    assert exc_info.value.line_no == sample_protocol.splitlines().index(TASK_ROW) + 1
