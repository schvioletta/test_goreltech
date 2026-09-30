import json

import httpx
import pytest

from app.llm import DeepSeekClient, LLMError, load_env_file
from app.rate_limit import SlidingWindowLimiter


def _client(handler) -> DeepSeekClient:
    return DeepSeekClient(api_key="test-key", transport=httpx.MockTransport(handler))


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def test_chat_sends_openai_compatible_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return _ok("ответ")

    client = _client(handler)
    assert client.chat([{"role": "user", "content": "привет"}], temperature=0.2, json_mode=True) == "ответ"
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "deepseek-chat"
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"] == [{"role": "user", "content": "привет"}]


def test_chat_without_json_mode_has_no_response_format():
    bodies = []
    _client(lambda r: bodies.append(json.loads(r.content)) or _ok("x")).chat([{"role": "user", "content": "q"}])
    assert "response_format" not in bodies[0]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": {"message": "bad key"}}),
        httpx.Response(500, text="oops"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}),
    ],
    ids=["401", "500", "not-json", "no-choices", "empty-content"],
)
def test_chat_errors_raise_llm_error(response):
    with pytest.raises(LLMError):
        _client(lambda r: response).chat([{"role": "user", "content": "q"}])


def test_chat_network_error_raises_llm_error():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(LLMError):
        _client(handler).chat([{"role": "user", "content": "q"}])


def test_error_message_does_not_leak_key_or_body():
    with pytest.raises(LLMError) as exc_info:
        _client(lambda r: httpx.Response(401, text="secret details")).chat([{"role": "user", "content": "q"}])
    assert "test-key" not in str(exc_info.value)
    assert "secret details" not in str(exc_info.value)


def test_from_env(monkeypatch):
    assert DeepSeekClient.from_env() is None
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    client = DeepSeekClient.from_env()
    assert client.api_key == "k"
    assert client.model == "deepseek-reasoner"


def test_load_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nexport A_KEY="quoted"\nB_KEY=plain\nEXISTING=from-file\nbroken line\n', encoding="utf-8")
    monkeypatch.delenv("A_KEY", raising=False)
    monkeypatch.delenv("B_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from-env")

    load_env_file(env)
    import os

    assert os.environ["A_KEY"] == "quoted"
    assert os.environ["B_KEY"] == "plain"
    assert os.environ["EXISTING"] == "from-env"
    load_env_file(tmp_path / "missing.env")


def test_sliding_window_limiter():
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 60.0
    assert limiter.allow("a")
