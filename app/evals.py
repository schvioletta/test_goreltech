"""Eval скила meeting-protocol на живой LLM: классификатор по eval_queries.md и генерация по примеру заметок.

Запуск: python -m app.evals [--generate]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.llm import ChatModel, DeepSeekClient, LLMError, load_env_file
from app.registry import SkillRegistry
from app.skill_runner import GenerationFormatError, classify, generate_protocol

EVAL_FILE = Path(__file__).resolve().parent.parent / "eval_queries.md"
SKILL_UNDER_TEST = "meeting-protocol"

ROW_RE = re.compile(r"^\| (\d+) \| (.+?) \| (Триггер(?: \+ route)?|Нет) \| (.+?) \|$")


@dataclass(frozen=True)
class EvalQuery:
    id: int
    query: str
    expected_skill: str | None
    expects_route: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "expected_skill": self.expected_skill,
            "expects_route": self.expects_route,
            "reason": self.reason,
        }


def load_eval_queries(path: Path = EVAL_FILE) -> list[EvalQuery]:
    queries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        expectation = m.group(3)
        queries.append(
            EvalQuery(
                id=int(m.group(1)),
                query=m.group(2).strip(),
                expected_skill=None if expectation == "Нет" else SKILL_UNDER_TEST,
                expects_route=expectation.endswith("route"),
                reason=m.group(4).strip(),
            )
        )
    return queries


def load_example_notes(path: Path = EVAL_FILE) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("### Входной запрос", 1)[1].split("```", 2)[1].strip()


def run_classifier_eval(registry: SkillRegistry, llm: ChatModel, queries: list[EvalQuery]) -> int:
    skills = registry.list()
    passed = 0
    print(f"Классификатор ({llm.model}), скилов в реестре: {len(skills)}\n")
    for q in queries:
        try:
            got = classify(q.query, skills, llm)
        except LLMError as exc:
            got, ok = f"ошибка: {exc}", False
        else:
            ok = got == q.expected_skill
        passed += ok
        mark = "✓" if ok else "✗"
        expected = q.expected_skill or "—"
        print(f"{mark} {q.id:>2}. ожидался {expected:<17} получен {got or '—':<17} {q.query[:70]}")
    print(f"\nИтого: {passed}/{len(queries)}")
    return passed


def run_generation_eval(registry: SkillRegistry, llm: ChatModel) -> bool:
    skill = registry.get(SKILL_UNDER_TEST)
    if skill is None:
        print(f"Скил {SKILL_UNDER_TEST} не загружен")
        return False
    started = time.monotonic()
    try:
        result = generate_protocol(load_example_notes(), skill, llm)
    except GenerationFormatError as exc:
        print(f"\nГенерация: ✗ {exc}\n\n{exc.last_output}")
        return False
    print(f"\nГенерация: ✓ формат валиден, попыток: {result.attempts}, {time.monotonic() - started:.1f} с\n")
    print(result.markdown)
    return result.is_protocol


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eval скила meeting-protocol на DeepSeek")
    parser.add_argument("--generate", action="store_true", help="также сгенерировать протокол по примеру заметок")
    parser.add_argument("--skills-dir", default="skills")
    args = parser.parse_args(argv)

    load_env_file()
    llm = DeepSeekClient.from_env()
    if llm is None:
        print("Не задан DEEPSEEK_API_KEY (переменная окружения или файл .env)", file=sys.stderr)
        return 2

    registry = SkillRegistry(args.skills_dir)
    queries = load_eval_queries()
    ok = run_classifier_eval(registry, llm, queries) == len(queries)
    if args.generate:
        ok = run_generation_eval(registry, llm) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
