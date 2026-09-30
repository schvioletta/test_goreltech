import logging
import threading
import time

from app.registry import SkillRegistry
from tests.conftest import ROOT, skill_md, write_skill


def test_valid_skill_loaded(tmp_path):
    write_skill(tmp_path, "demo-skill", skill_md(), {"references/format.md": "x"})
    registry = SkillRegistry(tmp_path)
    skill = registry.get("demo-skill")
    assert skill is not None
    assert skill.caption == "Демо"
    assert skill.description == "Когда применять."
    assert skill.body == "Тело промпта."
    assert skill.has_files is True
    assert skill.to_meta() == {
        "name": "demo-skill", "caption": "Демо", "description": "Когда применять.", "has_files": True,
    }


def test_name_from_folder_and_caption_default(tmp_path):
    write_skill(tmp_path, "from-folder", skill_md(name=None, caption=None))
    skill = SkillRegistry(tmp_path).get("from-folder")
    assert skill is not None
    assert skill.caption == "from-folder"
    assert skill.has_files is False


def test_multiline_description(tmp_path):
    content = "---\nname: multi\ndescription: >\n  Первая строка\n  вторая строка.\n---\nТело\n"
    write_skill(tmp_path, "multi", content)
    assert SkillRegistry(tmp_path).get("multi").description == "Первая строка вторая строка."


def test_invalid_skills_skipped_with_warning(tmp_path, caplog):
    write_skill(tmp_path, "good", skill_md(name="good"))
    write_skill(tmp_path, "bad-name", skill_md(name="Bad_Name"))
    write_skill(tmp_path, "long-name", skill_md(name="a" * 65))
    write_skill(tmp_path, "empty-body", skill_md(name="empty-body", body="   \n"))
    write_skill(tmp_path, "long-desc", skill_md(name="long-desc", description="x" * 1025))
    write_skill(tmp_path, "no-desc", skill_md(name="no-desc", description=None))
    write_skill(tmp_path, "no-skill-md", None, {"notes.txt": "x"})
    write_skill(tmp_path, "broken-yaml", "---\nname: [oops\ndescription: x\n---\nТело\n")
    write_skill(tmp_path, "unclosed", "---\nname: unclosed\ndescription: x\nТело\n")
    write_skill(tmp_path, "not-mapping", "---\n- a\n- b\n---\nТело\n")
    write_skill(tmp_path, "no-frontmatter", "Просто текст без метаданных.\n")
    write_skill(tmp_path, "desc-not-str", "---\nname: desc-not-str\ndescription: 42\n---\nТело\n")

    with caplog.at_level(logging.WARNING, logger="app.registry"):
        registry = SkillRegistry(tmp_path)

    assert [s.name for s in registry.list()] == ["good"]
    warned = {r.getMessage() for r in caplog.records if r.levelno == logging.WARNING}
    for dirname in ("bad-name", "long-name", "empty-body", "long-desc", "no-desc", "no-skill-md",
                    "broken-yaml", "unclosed", "not-mapping", "no-frontmatter", "desc-not-str"):
        assert any(dirname in msg for msg in warned), dirname


def test_description_exactly_limit_is_valid(tmp_path):
    write_skill(tmp_path, "edge", skill_md(name="edge", description="x" * 1024))
    assert SkillRegistry(tmp_path).get("edge") is not None


def test_duplicate_name_skipped(tmp_path, caplog):
    write_skill(tmp_path, "a-dir", skill_md(name="same"))
    write_skill(tmp_path, "b-dir", skill_md(name="same"))
    with caplog.at_level(logging.WARNING, logger="app.registry"):
        registry = SkillRegistry(tmp_path)
    assert len(registry) == 1
    assert registry.get("same").path.name == "a-dir"
    assert any("уже занято" in r.getMessage() for r in caplog.records)


def test_missing_root_gives_empty_registry(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="app.registry"):
        registry = SkillRegistry(tmp_path / "nope")
    assert registry.list() == []
    assert caplog.records


def test_search_case_insensitive_by_name_and_caption(tmp_path):
    write_skill(tmp_path, "meeting-protocol", skill_md(name="meeting-protocol", caption="Протокол встречи"))
    write_skill(tmp_path, "translator", skill_md(name="translator", caption="Переводчик"))
    registry = SkillRegistry(tmp_path)
    assert [s.name for s in registry.list("MEETING")] == ["meeting-protocol"]
    assert [s.name for s in registry.list("протокол")] == ["meeting-protocol"]
    assert [s.name for s in registry.list("ПЕРЕВОД")] == ["translator"]
    assert registry.list("нет-такого") == []
    assert len(registry.list("  ")) == 2


def test_reload_picks_up_changes(tmp_path):
    write_skill(tmp_path, "one", skill_md(name="one"))
    registry = SkillRegistry(tmp_path)
    assert registry.get("two") is None
    write_skill(tmp_path, "two", skill_md(name="two"))
    assert registry.reload() == 2
    assert registry.get("two") is not None


def test_reads_are_safe_during_reload(tmp_path):
    for i in range(20):
        write_skill(tmp_path, f"skill-{i}", skill_md(name=f"skill-{i}"))
    registry = SkillRegistry(tmp_path)
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                assert len(registry.list()) == 20
                assert registry.get("skill-5") is not None
                time.sleep(0)  # отдаём GIL, иначе сканирование диска в reload() сильно тормозит
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for _ in range(10):
        registry.reload()
    stop.set()
    for t in threads:
        t.join()
    assert errors == []


def test_repository_skill_is_valid():
    skill = SkillRegistry(ROOT / "skills").get("meeting-protocol")
    assert skill is not None
    assert skill.caption == "Протокол встречи"
    assert skill.has_files is True
    assert len(skill.description) <= 1024
