import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.api import DOCX_MEDIA_TYPE, create_app

DESCRIPTION = "Когда применять демо-скил."


@pytest.fixture
def client(make_skill, skills_root):
    make_skill(name="meeting-protocol", caption="Протокол встречи", files={"routes/a.md": "x"})
    make_skill(name="translator", caption="Переводчик")
    make_skill(name="Broken Name", dirname="broken")
    return TestClient(create_app(skills_root))


def test_list_skills(client):
    resp = client.get("/skills")
    assert resp.status_code == 200
    assert resp.json() == [
        {"name": "meeting-protocol", "caption": "Протокол встречи", "description": DESCRIPTION, "has_files": True},
        {"name": "translator", "caption": "Переводчик", "description": DESCRIPTION, "has_files": False},
    ]


def test_search_skills(client):
    assert [s["name"] for s in client.get("/skills", params={"q": "ПРОТОКОЛ"}).json()] == ["meeting-protocol"]
    assert client.get("/skills", params={"q": "zzz"}).json() == []


def test_get_skill_and_404(client):
    resp = client.get("/skills/translator")
    assert resp.status_code == 200
    assert resp.json()["body"] == "Тело системного промпта."
    assert client.get("/skills/nope").status_code == 404


def test_reload(client, make_skill):
    make_skill(name="new-skill")
    assert client.get("/skills/new-skill").status_code == 404
    assert client.post("/skills/reload").json() == {"status": "ok", "count": 3}
    assert client.get("/skills/new-skill").status_code == 200


def test_protocol_docx(client, sample_protocol):
    resp = client.post("/protocol/docx", json={"markdown": sample_protocol})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == DOCX_MEDIA_TYPE
    assert resp.headers["content-disposition"] == 'attachment; filename="protocol.docx"'
    doc = Document(io.BytesIO(resp.content))
    assert doc.paragraphs[0].text == "Протокол встречи: Планирование релиза v2.0"


@pytest.mark.parametrize("kwargs", [
    {"json": {}},
    {"json": {"markdown": ""}},
    {"json": {"markdown": "   "}},
    {"json": {"markdown": 123}},
    {"json": ["markdown"]},
    {"content": b"not json", "headers": {"content-type": "application/json"}},
])
def test_protocol_docx_bad_request(client, kwargs):
    assert client.post("/protocol/docx", **kwargs).status_code == 400


def test_protocol_docx_invalid_format(client):
    resp = client.post("/protocol/docx", json={"markdown": "# Просто заголовок"})
    assert resp.status_code == 422
    assert "формату" in resp.json()["detail"]
