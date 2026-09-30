import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.api import DOCX_MEDIA_TYPE, create_app
from tests.conftest import skill_md, write_skill


@pytest.fixture
def skills_root(tmp_path):
    write_skill(tmp_path, "meeting-protocol",
                skill_md(name="meeting-protocol", caption="Протокол встречи"), {"routes/a.md": "x"})
    write_skill(tmp_path, "translator", skill_md(name="translator", caption="Переводчик"))
    write_skill(tmp_path, "broken", skill_md(name="Broken Name"))
    return tmp_path


@pytest.fixture
def client(skills_root):
    return TestClient(create_app(skills_root))


def test_list_skills(client):
    resp = client.get("/skills")
    assert resp.status_code == 200
    assert resp.json() == [
        {"name": "meeting-protocol", "caption": "Протокол встречи", "description": "Когда применять.",
         "has_files": True},
        {"name": "translator", "caption": "Переводчик", "description": "Когда применять.", "has_files": False},
    ]


def test_search_skills(client):
    assert [s["name"] for s in client.get("/skills", params={"q": "ПРОТОКОЛ"}).json()] == ["meeting-protocol"]
    assert client.get("/skills", params={"q": "zzz"}).json() == []


def test_get_skill_and_404(client):
    resp = client.get("/skills/translator")
    assert resp.status_code == 200
    assert resp.json()["body"] == "Тело промпта."
    assert client.get("/skills/nope").status_code == 404


def test_reload(client, skills_root):
    write_skill(skills_root, "new-skill", skill_md(name="new-skill"))
    assert client.get("/skills/new-skill").status_code == 404
    resp = client.post("/skills/reload")
    assert resp.json() == {"status": "ok", "count": 3}
    assert client.get("/skills/new-skill").status_code == 200


def test_protocol_docx(client, valid_protocol):
    resp = client.post("/protocol/docx", json={"markdown": valid_protocol})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == DOCX_MEDIA_TYPE
    assert resp.headers["content-disposition"] == 'attachment; filename="protocol.docx"'
    doc = Document(io.BytesIO(resp.content))
    assert doc.paragraphs[0].text == "Протокол встречи: Планирование релиза"


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
