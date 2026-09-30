"""Минимальный клиент DeepSeek (OpenAI-совместимый Chat Completions API) на httpx."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 120.0

Message = dict[str, str]


class LLMError(RuntimeError):
    """Ошибка обращения к LLM: сеть, таймаут, не-2xx ответ или неожиданный формат ответа."""


class LLMNotConfigured(LLMError):
    """Не задан DEEPSEEK_API_KEY."""


class ChatModel(Protocol):
    model: str

    def chat(self, messages: list[Message], *, temperature: float = 0.0, json_mode: bool = False) -> str: ...


def load_env_file(path: str | Path = ".env") -> None:
    """Подхватывает KEY=VALUE из .env, не перетирая уже заданные переменные окружения."""
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass
class DeepSeekClient:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    transport: httpx.BaseTransport | None = None

    @classmethod
    def from_env(cls) -> DeepSeekClient | None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        )

    def chat(self, messages: list[Message], *, temperature: float = 0.0, json_mode: bool = False) -> str:
        payload: dict = {"model": self.model, "messages": messages, "temperature": temperature, "stream": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
                resp = client.post(
                    "/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"не удалось обратиться к LLM: {exc.__class__.__name__}") from exc

        if resp.status_code != 200:
            # Тело ответа не пробрасываем целиком: в нём может оказаться служебная информация провайдера.
            raise LLMError(f"LLM вернула HTTP {resp.status_code}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("неожиданный формат ответа LLM") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM вернула пустой ответ")
        return content
