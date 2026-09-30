import logging
import shutil
import threading
import time

import pytest

from app.registry import SkillRegistry
from tests.conftest import ROOT

LOGGER = "app.registry"


def _names(registry: SkillRegistry, q: str | None = None) -> list[str]:
    return [skill.name for skill in registry.list(q)]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]


def test_valid_skill_loaded(make_skill, skills_root):
    make_skill(name="meeting-protocol", caption="Протокол встречи", body="Ты — секретарь.")
    skill = SkillRegistry(skills_root).get("meeting-protocol")

    assert skill is not None
    assert skill.name == "meeting-protocol"
    assert skill.caption == "Протокол встречи"
    assert skill.description == "Когда применять демо-скил."
    assert skill.body == "Ты — секретарь."
    assert skill.path == skills_root / "meeting-protocol"
    assert skill.to_meta() == {
        "name": "meeting-protocol",
        "caption": "Протокол встречи",
        "description": "Когда применять демо-скил.",
        "has_files": False,
    }


def test_has_files_true_with_references(make_skill, skills_root):
    make_skill(name="with-refs", files={"references/format.md": "контракт"})
    make_skill(name="plain")
    registry = SkillRegistry(skills_root)

    assert registry.get("with-refs").has_files is True
    assert registry.get("plain").has_files is False


def test_has_files_ignores_empty_dirs_and_hidden_files(make_skill, skills_root):
    skill_dir = make_skill(name="only-hidden", files={".DS_Store": "x"})
    (skill_dir / "routes").mkdir()
    assert SkillRegistry(skills_root).get("only-hidden").has_files is False


def test_invalid_name_skipped_with_kebab_case_warning(make_skill, skills_root, caplog):
    make_skill(name="Bad Name", dirname="bad-name")
    make_skill(name="good-skill")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(skills_root)

    assert _names(registry) == ["good-skill"]
    assert any("bad-name" in msg and "kebab-case" in msg for msg in _warnings(caplog))


def test_name_longer_than_64_skipped(make_skill, skills_root, caplog):
    make_skill(name="a" * 65, dirname="too-long")
    make_skill(name="b" * 64, dirname="exactly-64")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(skills_root)

    assert _names(registry) == ["b" * 64]
    assert any("too-long" in msg for msg in _warnings(caplog))


@pytest.mark.parametrize("body", ["", "   ", "\n\n\t\n"])
def test_empty_body_skipped(make_skill, skills_root, caplog, body):
    make_skill(name="empty-body", body=body)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(skills_root)

    assert registry.get("empty-body") is None
    assert any("empty-body" in msg for msg in _warnings(caplog))


def test_too_long_description_skipped(make_skill, skills_root, caplog):
    make_skill(name="long-desc", description="x" * 1025)
    make_skill(name="limit-desc", description="x" * 1024)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(skills_root)

    assert _names(registry) == ["limit-desc"]
    assert any("long-desc" in msg and "1024" in msg for msg in _warnings(caplog))


def test_missing_description_skipped(make_skill, skills_root, caplog):
    make_skill(name="no-desc", description=None)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(skills_root)

    assert len(registry) == 0
    assert any("no-desc" in msg and "description" in msg for msg in _warnings(caplog))


def test_dir_without_skill_md_skipped(make_skill, skills_root, caplog):
    make_skill(name="no-skill-md", with_skill_md=False, files={"references/notes.md": "x"})
    make_skill(name="good-skill")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(skills_root)

    assert _names(registry) == ["good-skill"]
    assert any("no-skill-md" in msg and "SKILL.md" in msg for msg in _warnings(caplog))


def test_name_taken_from_folder_when_missing(make_skill, skills_root):
    make_skill(name=None, caption=None, dirname="folder-name")
    skill = SkillRegistry(skills_root).get("folder-name")

    assert skill is not None
    assert skill.name == "folder-name"
    assert skill.caption == "folder-name"


@pytest.mark.parametrize(
    "frontmatter",
    [
        'name: [unclosed\ndescription: "x"',
        "- just\n- a list",
        'name: "not-str-desc"\ndescription: 42',
    ],
    ids=["broken-yaml", "not-a-mapping", "description-not-string"],
)
def test_broken_frontmatter_skipped(make_skill, skills_root, caplog, frontmatter):
    make_skill(dirname="broken", frontmatter=frontmatter)
    make_skill(name="good-skill")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(skills_root)

    assert _names(registry) == ["good-skill"]
    assert any("broken" in msg for msg in _warnings(caplog))


def test_search_by_name_and_caption(make_skill, skills_root):
    make_skill(name="meeting-protocol", caption="Протокол встречи")
    make_skill(name="translator", caption="Переводчик")
    registry = SkillRegistry(skills_root)

    assert _names(registry, "meet") == ["meeting-protocol"]
    assert _names(registry, "Протокол") == ["meeting-protocol"]
    assert _names(registry, "протокол") == ["meeting-protocol"]
    assert _names(registry, "MEET") == ["meeting-protocol"]
    assert _names(registry, "nope") == []
    assert _names(registry) == ["meeting-protocol", "translator"]


def test_reload_after_remove_and_add(make_skill, skills_root):
    make_skill(name="alpha")
    beta_dir = make_skill(name="beta")
    registry = SkillRegistry(skills_root)
    assert _names(registry) == ["alpha", "beta"]

    shutil.rmtree(beta_dir)
    make_skill(name="gamma")
    count = registry.reload()

    assert count == 2
    assert _names(registry) == ["alpha", "gamma"]
    assert registry.get("beta") is None
    assert registry.get("gamma") is not None


def test_reload_is_thread_safe(make_skill, skills_root):
    for i in range(10):
        make_skill(name=f"skill-{i}", files={"references/a.md": "x"} if i % 2 else None)
    registry = SkillRegistry(skills_root)
    expected = _names(registry)
    assert len(expected) == 10

    errors: list[BaseException] = []
    stop = threading.Event()
    started = threading.Barrier(5)

    def reader() -> None:
        try:
            started.wait()
            while not stop.is_set():
                assert _names(registry) == expected
                assert registry.get("skill-3") is not None
                time.sleep(0)  # отдаём GIL, чтобы reload() не голодал на файловом I/O
        except BaseException as exc:  # noqa: BLE001 — собираем любые ошибки потоков
            errors.append(exc)

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        started.wait()
        for _ in range(50):
            registry.reload()
    except BaseException as exc:  # noqa: BLE001
        errors.append(exc)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=10)

    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert _names(registry) == expected


def test_missing_root_gives_empty_registry(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        registry = SkillRegistry(tmp_path / "does-not-exist")
    assert registry.list() == []
    assert _warnings(caplog)


def test_repository_skill_is_valid():
    skill = SkillRegistry(ROOT / "skills").get("meeting-protocol")
    assert skill is not None
    assert skill.caption == "Протокол встречи"
    assert skill.has_files is True
