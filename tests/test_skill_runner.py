import pytest

from app.evals import SKILL_UNDER_TEST, load_eval_queries, load_example_notes
from app.llm import LLMError
from app.registry import SkillRegistry
from app.skill_runner import (
    CLASSIFIER_DESCRIPTION_LIMIT,
    MAX_GENERATION_ATTEMPTS,
    GenerationFormatError,
    build_classifier_prompt,
    build_system_prompt,
    classify,
    generate_protocol,
    wants_quick_summary,
)
from tests.conftest import ROOT

SUMMARY = "\n## Краткое резюме\n\n- Релиз перенесён на 12.11.2025.\n- Ответственный за release notes не указан.\n- Выбор аналитики открыт.\n"


@pytest.fixture(scope="module")
def skill():
    return SkillRegistry(ROOT / "skills").get(SKILL_UNDER_TEST)


def test_system_prompt_contains_body_and_reference(skill):
    prompt = build_system_prompt(skill, quick_summary=False)
    assert prompt.startswith(skill.body)
    assert "references/protocol_format.md" in prompt
    assert "routes/quick_summary.md\n\n" not in prompt


def test_system_prompt_adds_route_for_quick_summary(skill):
    prompt = build_system_prompt(skill, quick_summary=True)
    assert "# Активный сценарий: routes/quick_summary.md" in prompt
    assert "## Краткое резюме" in prompt


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Кратко: что решили?", True),
        ("TL;DR по созвону", True),
        ("tldr please", True),
        ("опиши в двух словах", True),
        ("Оформи протокол по заметкам", False),
        ("Краткость — сестра таланта", False),
    ],
)
def test_wants_quick_summary(text, expected):
    assert wants_quick_summary(text) is expected


def test_generate_valid_first_try(skill, fake_llm_factory, sample_protocol):
    llm = fake_llm_factory(sample_protocol)
    result = generate_protocol("заметки о встрече", skill, llm)

    assert result.is_protocol and result.attempts == 1 and not result.quick_summary
    assert result.markdown == sample_protocol.strip()
    system, user = llm.calls[0]["messages"]
    assert system["role"] == "system" and system["content"].startswith(skill.body)
    assert user == {"role": "user", "content": "заметки о встрече"}


def test_generate_repairs_format_error(skill, fake_llm_factory, sample_protocol):
    broken = sample_protocol.replace("24.10.2025", "скоро")
    llm = fake_llm_factory(broken, sample_protocol)
    result = generate_protocol("заметки", skill, llm)

    assert result.is_protocol and result.attempts == 2
    repair_messages = llm.calls[1]["messages"]
    assert repair_messages[-2] == {"role": "assistant", "content": broken.strip()}
    assert "срок должен быть" in repair_messages[-1]["content"]


def test_generate_repairs_code_fence(skill, fake_llm_factory, sample_protocol):
    llm = fake_llm_factory(f"```markdown\n{sample_protocol}```", sample_protocol)
    assert generate_protocol("заметки", skill, llm).attempts == 2
    assert "обёртки в блок кода" in llm.calls[1]["messages"][-1]["content"]


def test_generate_gives_up_after_max_attempts(skill, fake_llm_factory, sample_protocol):
    broken = sample_protocol.replace("## Решения", "## Итоги")
    llm = fake_llm_factory(*([broken] * MAX_GENERATION_ATTEMPTS))
    with pytest.raises(GenerationFormatError) as exc_info:
        generate_protocol("заметки", skill, llm)
    assert exc_info.value.attempts == MAX_GENERATION_ATTEMPTS
    assert exc_info.value.last_output == broken.strip()
    assert len(llm.calls) == MAX_GENERATION_ATTEMPTS


def test_generate_returns_clarifying_question(skill, fake_llm_factory):
    llm = fake_llm_factory("Пришлите, пожалуйста, заметки о встрече.")
    result = generate_protocol("оформи протокол", skill, llm)
    assert not result.is_protocol
    assert result.markdown == "Пришлите, пожалуйста, заметки о встрече."


def test_generate_quick_summary_requires_summary_section(skill, fake_llm_factory, sample_protocol):
    llm = fake_llm_factory(sample_protocol, sample_protocol + SUMMARY)
    result = generate_protocol("Кратко, TL;DR: заметки", skill, llm)

    assert result.quick_summary and result.attempts == 2
    assert "routes/quick_summary.md" in llm.calls[0]["messages"][0]["content"]
    assert "Краткое резюме" in llm.calls[1]["messages"][-1]["content"]


def test_generate_propagates_llm_error(skill, fake_llm_factory):
    with pytest.raises(LLMError):
        generate_protocol("заметки", skill, fake_llm_factory(LLMError("HTTP 500")))


def test_classifier_prompt_truncates_descriptions(make_skill, skills_root):
    make_skill(name="long-one", description="д" * 600)
    prompt = build_classifier_prompt(SkillRegistry(skills_root).list())
    assert "- long-one: " + "д" * CLASSIFIER_DESCRIPTION_LIMIT + "\n" in prompt + "\n"
    assert "д" * (CLASSIFIER_DESCRIPTION_LIMIT + 1) not in prompt


@pytest.mark.parametrize(
    "response, expected",
    [
        ('{"skill": "meeting-protocol"}', "meeting-protocol"),
        ('{"skill": "none"}', None),
        ('{"skill": "unknown-skill"}', None),
        ('{"skill": null}', None),
        ('{"other": 1}', None),
    ],
)
def test_classify_parses_response(skill, fake_llm_factory, response, expected):
    llm = fake_llm_factory(response)
    assert classify("запрос", [skill], llm) == expected
    assert llm.calls[0]["json_mode"] is True and llm.calls[0]["temperature"] == 0.0


def test_classify_non_json_raises(skill, fake_llm_factory):
    with pytest.raises(LLMError):
        classify("запрос", [skill], fake_llm_factory("meeting-protocol"))


def test_classify_without_skills_skips_llm(fake_llm_factory):
    llm = fake_llm_factory()
    assert classify("запрос", [], llm) is None
    assert llm.calls == []


def test_eval_file_parsed():
    queries = load_eval_queries()
    assert [q.id for q in queries] == list(range(1, 11))
    assert sum(q.expected_skill == SKILL_UNDER_TEST for q in queries) == 6
    assert sum(q.expected_skill is None for q in queries) == 4
    assert [q.id for q in queries if q.expects_route] == [6]
    assert load_example_notes().startswith("Оформи протокол по заметкам:")
