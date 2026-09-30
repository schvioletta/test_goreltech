import io

from docx import Document
from docx.shared import Pt

from app.docx_generator import build_docx, main, protocol_to_docx_bytes, protocol_to_docx_file
from app.protocol_parser import Protocol, Task, parse_protocol

H2 = ["Метаданные", "Обсуждение", "Решения", "Задачи", "Риски и открытые вопросы"]


def _load(data: bytes):
    return Document(io.BytesIO(data))


def _headings(doc, level: int) -> list[str]:
    return [p.text for p in doc.paragraphs if p.style.name == f"Heading {level}"]


def test_document_structure(valid_protocol):
    data = protocol_to_docx_bytes(valid_protocol)
    assert data[:2] == b"PK"
    doc = _load(data)
    assert _headings(doc, 1) == ["Протокол встречи: Планирование релиза"]
    assert _headings(doc, 2) == H2
    assert _headings(doc, 3) == ["Дата релиза", "Аналитика"]

    assert len(doc.tables) == 1
    rows = [[c.text for c in r.cells] for r in doc.tables[0].rows]
    assert rows == [
        ["Задача", "Ответственный", "Срок"],
        ["Подготовить план регресса", "Игорь Петров", "31.10.2025"],
        ["Обновить release notes", "не указан", "не указан"],
    ]
    texts = [p.text for p in doc.paragraphs]
    assert "Дата: 14.10.2025" in texts
    assert "Перенести релиз на 12.11.2025." in texts
    numbered = [p.text for p in doc.paragraphs if p.style.name == "List Number"]
    assert numbered == ["Перенести релиз на 12.11.2025.", "Включить пуш-уведомления в релиз."]


def test_styles_and_margins(valid_protocol):
    doc = _load(protocol_to_docx_bytes(valid_protocol))
    sizes = {"Normal": 11, "Heading 1": 16, "Heading 2": 13, "Heading 3": 11}
    for name, size in sizes.items():
        assert doc.styles[name].font.name == "Calibri"
        assert doc.styles[name].font.size == Pt(size)
    section = doc.sections[0]
    # Word хранит поля в твипах, поэтому сравниваем с точностью до сотых сантиметра.
    assert [round(m.cm, 2) for m in (section.top_margin, section.bottom_margin)] == [2.0, 2.0]
    assert [round(m.cm, 2) for m in (section.left_margin, section.right_margin)] == [1.5, 1.5]


def test_empty_sections_get_placeholder(empty_protocol):
    doc = _load(protocol_to_docx_bytes(empty_protocol))
    assert _headings(doc, 2) == H2
    assert doc.tables == []
    texts = [p.text for p in doc.paragraphs]
    assert texts.count("— не указано —") == 4
    assert "Участники: не указано" in texts


def test_missing_fields_in_objects_filled_with_placeholders():
    protocol = Protocol(
        title="",
        metadata={"Дата": "01.02.2026"},
        tasks=[Task("Сделать отчёт", owner="", due="  ")],
    )
    buffer = io.BytesIO()
    build_docx(protocol).save(buffer)
    doc = _load(buffer.getvalue())
    assert _headings(doc, 1) == ["Протокол встречи: не указано"]
    assert [c.text for c in doc.tables[0].rows[1].cells] == ["Сделать отчёт", "не указан", "не указан"]
    texts = [p.text for p in doc.paragraphs]
    assert "Место: не указано" in texts
    assert texts.count("— не указано —") == 3


def test_summary_section_rendered(valid_protocol):
    doc = _load(protocol_to_docx_bytes(valid_protocol + "\n## Краткое резюме\n\n- Коротко.\n"))
    assert _headings(doc, 2) == H2 + ["Краткое резюме"]


def test_file_and_cli(tmp_path, valid_protocol, capsys):
    out = protocol_to_docx_file(valid_protocol, tmp_path / "sub" / "a.docx")
    assert out.exists()
    src = tmp_path / "in.md"
    src.write_text(valid_protocol, encoding="utf-8")
    assert main([str(src), str(tmp_path / "b.docx")]) == 0
    assert (tmp_path / "b.docx").exists()
    src.write_text("не протокол", encoding="utf-8")
    assert main([str(src), str(tmp_path / "c.docx")]) == 1
    assert "Ошибка" in capsys.readouterr().err
    assert parse_protocol(valid_protocol).title == "Планирование релиза"
