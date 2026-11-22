"""Authoring budgets for every skill in every plugin.

The checks live in create-skill's scripts/check_skill.py so the same code runs
here and against a skill folder anywhere (uv run --script).
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "plugins" / "core" / "skills" / "create-skill" / "scripts" / "check_skill.py"

_spec = importlib.util.spec_from_file_location("check_skill", CHECKER)
check_skill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_skill)

# A folder with no SKILL.md (only references/) is a skill a later task has not created yet.
SKILLS = sorted(p.parent for p in ROOT.glob("plugins/*/skills/*/SKILL.md"))
IDS = [f"{s.parent.parent.name}:{s.name}" for s in SKILLS]


def _assert_clean(problems):
    assert not problems, "\n".join(problems)


def test_skills_found():
    names = {s.name for s in SKILLS}
    assert {"create-skill", "create-hook", "config-audit"} <= names


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_description_budget(skill):
    _assert_clean(check_skill.check_description(skill))


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_body_budget(skill):
    _assert_clean(check_skill.check_body(skill))


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_reference_budget(skill):
    _assert_clean(check_skill.check_references(skill))


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_references_are_linked(skill):
    _assert_clean(check_skill.check_linked(skill))


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_dispatches_name_a_model(skill):
    _assert_clean(check_skill.check_models(skill))


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_opus_only_in_allowed_roles(skill):
    _assert_clean(check_skill.check_opus(skill))


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_each_skill_has_evals(skill):
    _assert_clean(check_skill.check_evals(skill))


def test_checker_flags_violations(tmp_path):
    """The checks fail on a bad skill, so a green run means something."""
    skill = tmp_path / "bad"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: bad\ndescription: " + "x" * 401 + "\n---\n"
        + "Dispatch a subagent. Use opus.\n" + "line\n" * 150
    )
    (skill / "references" / "orphan.md").write_text("line\n" * 301)
    for check in check_skill.CHECKS:
        assert check(skill), check.__name__
    good = tmp_path / "good"
    (good / "evals" / "a").mkdir(parents=True)
    (good / "evals" / "b").mkdir()
    (good / "evals" / "a" / "prompt.md").write_text("p")
    (good / "evals" / "b" / "prompt.md").write_text("p")
    (good / "SKILL.md").write_text("---\nname: good\ndescription: Use when ok.\n---\nBody.\n")
    for check in check_skill.CHECKS:
        assert not check(good), check.__name__
