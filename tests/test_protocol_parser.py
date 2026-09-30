import pytest

from app.protocol_parser import (
    REQUIRED_SECTIONS,
    ProtocolParseError,
    Task,
    parse_protocol,
    validate_protocol,
)
from tests.conftest import ROOT


def test_parse_valid(valid_protocol):
    p = parse_protocol(valid_protocol)
    assert p.title == "Планирование релиза"
    assert p.metadata["Дата"] == "14.10.2025"
    assert list(p.metadata) == ["Дата", "Время", "Место", "Участники"]
    assert p.discussion == [
        ("Дата релиза", "Рассматривалась дата 10.11.\nЗафиксирована дата 12.11."),
        ("Аналитика", "Обсуждался переход на Amplitude."),
    ]
    assert p.decisions == ["Перенести релиз на 12.11.2025.", "Включить пуш-уведомления в релиз."]
    assert p.tasks == [
        Task("Подготовить план регресса", "Игорь Петров", "31.10.2025"),
        Task("Обновить release notes", "не указан", "не указан"),
    ]
    assert p.risks == ["Не назначен ответственный: обновить release notes."]
    assert p.summary is None


def test_parse_empty_sections(empty_protocol):
    p = parse_protocol(empty_protocol)
    assert p.title == "не указано"
    assert p.metadata == {"Дата": "не указано", "Время": "не указано", "Место": "не указано",
                          "Участники": "не указано"}
    assert (p.discussion, p.decisions, p.tasks, p.risks) == ([], [], [], [])


def test_parse_crlf_and_summary(valid_protocol):
    text = valid_protocol + "\n## Краткое резюме\n\n- Релиз 12.11.2025.\n"
    p = parse_protocol(text.replace("\n", "\r\n"))
    assert p.summary == ["Релиз 12.11.2025."]


def test_eval_example_parses():
    text = (ROOT / "eval_queries.md").read_text(encoding="utf-8")
    doc = text.split("### Ожидаемый ответ")[1].split("```")[1]
    p = parse_protocol(doc)
    assert len(p.tasks) == 5
    assert p.tasks[3] == Task("Обновить release notes для стора", "не указан", "не указан")


def test_validate_reports_missing_sections(valid_protocol):
    assert validate_protocol(valid_protocol) == []
    broken = valid_protocol.replace("## Решения", "## Итоги")
    assert validate_protocol(broken) == ["Решения"]
    assert validate_protocol("") == list(REQUIRED_SECTIONS)


@pytest.mark.parametrize(
    "old, new",
    [
        ("# Протокол встречи: Планирование релиза", "# Протокол: Планирование релиза"),
        ("## Решения", "## Итоги"),
        ("| Задача | Ответственный | Срок |", "| Задача | Ответственный | Срок | Статус |"),
        ("| --- | --- | --- |", "|---|---|---|"),
        ("| Подготовить план регресса | Игорь Петров | 31.10.2025 |",
         "| Подготовить план регресса | Игорь Петров | скоро |"),
        ("| Подготовить план регресса | Игорь Петров | 31.10.2025 |",
         "| Подготовить план регресса | Игорь Петров |"),
        ("2. Включить", "3. Включить"),
        ("- Не назначен ответственный", "* Не назначен ответственный"),
        ("### Аналитика", "#### Аналитика"),
        ("- Дата: 14.10.2025", "- Дата: 14 октября"),
        ("- Время: 11:00-12:00", "- Время: утром"),
        ("- Место: Zoom\n", ""),
        ("- Участники: Анна Смирнова (PM), Игорь Петров (QA)\n",
         "- Участники: Анна Смирнова (PM), Игорь Петров (QA)\n- Ведущий: Анна Смирнова\n"),
        ("- Место: Zoom\n- Участники: Анна Смирнова (PM), Игорь Петров (QA)\n",
         "- Участники: Анна Смирнова (PM), Игорь Петров (QA)\n- Место: Zoom\n"),
        ("Рассматривалась дата 10.11.", "- Рассматривалась дата 10.11."),
        ("Рассматривалась дата 10.11.", "1. Рассматривалась дата 10.11."),
        ("## Решения\n\n1. Перенести релиз на 12.11.2025.\n2. Включить пуш-уведомления в релиз.\n",
         "## Решения\n\n"),
        ("## Риски и открытые вопросы\n\n- Не назначен ответственный: обновить release notes.\n",
         "## Риски и открытые вопросы\n\n— не указано —\n- Лишний пункт\n"),
    ],
)
def test_strict_format_violations(valid_protocol, old, new):
    assert old in valid_protocol
    with pytest.raises(ProtocolParseError):
        parse_protocol(valid_protocol.replace(old, new))


def test_wrong_section_order(valid_protocol):
    a, b = "## Решения", "## Задачи"
    swapped = valid_protocol.replace(a, "@@").replace(b, a).replace("@@", b)
    with pytest.raises(ProtocolParseError):
        parse_protocol(swapped)


def test_text_before_title_rejected(valid_protocol):
    with pytest.raises(ProtocolParseError):
        parse_protocol("Вот ваш протокол:\n\n" + valid_protocol)


def test_h3_outside_discussion_rejected(valid_protocol):
    with pytest.raises(ProtocolParseError):
        parse_protocol(valid_protocol.replace("## Решения\n", "## Решения\n\n### Подтема\n"))


def test_discussion_text_without_topic_rejected(valid_protocol):
    with pytest.raises(ProtocolParseError):
        parse_protocol(valid_protocol.replace("## Обсуждение\n", "## Обсуждение\n\nТекст без темы.\n"))
