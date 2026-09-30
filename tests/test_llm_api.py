import pytest
from fastapi.testclient import TestClient

from app.api import MAX_NOTES_CHARS, create_app
from app.llm import LLMError
from app.rate_limit import SlidingWindowLimiter
from tests.conftest import ROOT

SKILLS_DIR = ROOT / "skills"


def _client(llm, **limiters) -> TestClient:
    return TestClient(create_app(SKILLS_DIR, llm=llm, **limiters))


def test_llm_status(fake_llm_factory):
    assert _client(None).get("/llm/status").json() == {"configured": False, "model": None}
    assert _client(fake_llm_factory()).get("/llm/status").json() == {"configured": True, "model": "fake-model"}


def test_generate_ok(fake_llm_factory, sample_protocol):
    resp = _client(fake_llm_factory(sample_protocol)).post("/protocol/generate", json={"notes": "заметки"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["markdown"] == sample_protocol.strip()
    assert body == {**body, "is_protocol": True, "attempts": 1, "quick_summary": False,
                    "skill": "meeting-protocol", "model": "fake-model"}


def test_generated_protocol_converts_to_docx(fake_llm_factory, sample_protocol):
    client = _client(fake_llm_factory(sample_protocol))
    markdown = client.post("/protocol/generate", json={"notes": "заметки"}).json()["markdown"]
    assert client.post("/protocol/docx", json={"markdown": markdown}).status_code == 200


def test_generate_without_llm_is_503():
    resp = _client(None).post("/protocol/generate", json={"notes": "заметки"})
    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]


@pytest.mark.parametrize("payload", [{}, {"notes": ""}, {"notes": "  "}, {"notes": "x" * (MAX_NOTES_CHARS + 1)}])
def test_generate_bad_request(fake_llm_factory, payload):
    llm = fake_llm_factory()
    assert _client(llm).post("/protocol/generate", json=payload).status_code == 400
    assert llm.calls == []


def test_generate_format_failure_is_422(fake_llm_factory, sample_protocol):
    broken = sample_protocol.replace("## Решения", "## Итоги")
    resp = _client(fake_llm_factory(broken, broken)).post("/protocol/generate", json={"notes": "заметки"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["attempts"] == 2
    assert detail["last_output"] == broken.strip()


def test_generate_llm_error_is_502(fake_llm_factory):
    resp = _client(fake_llm_factory(LLMError("HTTP 500"))).post("/protocol/generate", json={"notes": "заметки"})
    assert resp.status_code == 502


def test_rate_limit_per_ip(fake_llm_factory):
    llm = fake_llm_factory('{"skill": "none"}')
    client = _client(llm, per_ip_limiter=SlidingWindowLimiter(1, 60))
    assert client.post("/skills/classify", json={"query": "q"}).status_code == 200
    assert client.post("/skills/classify", json={"query": "q"}).status_code == 429
    assert len(llm.calls) == 1


def test_rate_limit_global(fake_llm_factory):
    llm = fake_llm_factory('{"skill": "none"}')
    client = _client(llm, global_limiter=SlidingWindowLimiter(1, 86_400))
    assert client.post("/skills/classify", json={"query": "q"}, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert client.post("/skills/classify", json={"query": "q"}, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429


def test_classify(fake_llm_factory):
    llm = fake_llm_factory('{"skill": "meeting-protocol"}', '{"skill": "none"}')
    client = _client(llm)
    assert client.post("/skills/classify", json={"query": "оформи протокол"}).json() == {
        "skill": "meeting-protocol", "model": "fake-model"}
    assert client.post("/skills/classify", json={"query": "переведи текст"}).json()["skill"] is None
    assert "meeting-protocol:" in llm.calls[0]["messages"][0]["content"]


def test_eval_queries_endpoint():
    queries = _client(None).get("/eval/queries").json()
    assert len(queries) == 10
    assert queries[0]["expected_skill"] == "meeting-protocol"
    assert queries[-1]["expected_skill"] is None


def test_openapi_has_llm_bodies():
    paths = _client(None).get("/openapi.json").json()["paths"]
    assert paths["/protocol/generate"]["post"]["requestBody"]["content"]["application/json"]["example"]["notes"]
    assert paths["/skills/classify"]["post"]["requestBody"]["content"]["application/json"]["schema"]["required"] == ["query"]
