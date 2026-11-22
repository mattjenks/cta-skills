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
# Skill dirs that hold only references/ until a later task adds the SKILL.md.
REFERENCES_ONLY = {"build/implement"}

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


def test_every_skill_dir_has_exact_skill_md():
    """A skill dir the budget tests would skip must be a known references-only dir."""
    for d in sorted(ROOT.glob("plugins/*/skills/*")):
        if not d.is_dir():
            continue
        key = f"{d.parent.parent.name}/{d.name}"
        names = {f.name for f in d.iterdir()}
        variants = {n for n in names if n.lower() == "skill.md" and n != "SKILL.md"}
        assert not variants, f"{key}: case-variant skill file {variants}"
        if "SKILL.md" not in names:
            assert key in REFERENCES_ONLY, f"{key}: no SKILL.md and not an allowed references-only dir"


# --- the checker itself: each negative case isolates one violation ---

def make_skill(tmp_path, *, description="Use when ok.", body_lines=1, body_text="", refs=None, evals=2):
    skill = tmp_path / "demo"
    skill.mkdir()
    head = f"---\nname: demo\ndescription: {description}\n---\n"
    lines = head.count("\n") + body_text.count("\n")
    filler = "x\n" * max(0, body_lines - lines)
    (skill / "SKILL.md").write_text(head + body_text + filler)
    for name, n in (refs or {}).items():
        (skill / "references").mkdir(exist_ok=True)
        (skill / "references" / name).write_text("line\n" * n)
    for i in range(evals):
        case = skill / "evals" / f"case-{i}"
        case.mkdir(parents=True)
        (case / "prompt.md").write_text("p")
    return skill


def test_clean_skill_passes_every_check(tmp_path):
    skill = make_skill(tmp_path, refs={"a.md": 5}, body_text="See a.md.\n")
    for check in check_skill.CHECKS:
        assert check(skill) == [], check.__name__


@pytest.mark.parametrize("n, ok", [(400, True), (401, False)])
def test_description_boundary(tmp_path, n, ok):
    problems = check_skill.check_description(make_skill(tmp_path, description="d" * n))
    assert (problems == []) is ok
    if not ok:
        assert problems == ["demo: description is 401 characters (1 to 400)"]


def test_description_missing(tmp_path):
    skill = make_skill(tmp_path)
    (skill / "SKILL.md").write_text("no frontmatter\n")
    assert check_skill.check_description(skill) == ["demo: description is 0 characters (1 to 400)"]


@pytest.mark.parametrize("n, ok", [(150, True), (151, False)])
def test_body_boundary(tmp_path, n, ok):
    problems = check_skill.check_body(make_skill(tmp_path, body_lines=n))
    assert (problems == []) is ok
    if not ok:
        assert problems == ["demo: SKILL.md is 151 lines (max 150)"]


@pytest.mark.parametrize("n, ok", [(300, True), (301, False)])
def test_reference_boundary(tmp_path, n, ok):
    problems = check_skill.check_references(make_skill(tmp_path, refs={"big.md": n}))
    assert (problems == []) is ok
    if not ok:
        assert problems == ["demo: references/big.md is 301 lines (max 300)"]


def test_unlinked_reference_flagged(tmp_path):
    skill = make_skill(tmp_path, refs={"linked.md": 1, "orphan.md": 1}, body_text="Read linked.md.\n")
    assert check_skill.check_linked(skill) == ["demo: references/orphan.md is not named in SKILL.md"]


def test_dispatch_without_model_flagged(tmp_path):
    skill = make_skill(tmp_path, body_text="Dispatch a subagent. See models.md.\n")
    assert check_skill.check_models(skill) == [
        "demo: dispatches a subagent without naming haiku, sonnet or opus"
    ]


def test_dispatch_without_models_link_flagged(tmp_path):
    skill = make_skill(tmp_path, body_text="Dispatch a subagent on sonnet.\n")
    assert check_skill.check_models(skill) == ["demo: dispatches a subagent without linking models.md"]


def test_dispatch_with_model_and_link_passes(tmp_path):
    skill = make_skill(tmp_path, body_text="Dispatch a subagent on sonnet (see models.md).\n")
    assert check_skill.check_models(skill) == []


def test_no_dispatch_needs_no_model(tmp_path):
    assert check_skill.check_models(make_skill(tmp_path, body_text="Plain text.\n")) == []


def test_opus_flagged_outside_allowed_roles(tmp_path):
    skill = make_skill(tmp_path, body_text="Use opus here.\n")
    assert check_skill.check_opus(skill) == ["demo: 'SKILL.md' mentions opus outside the allowed roles"]


def test_opus_allowed_in_fix_loop_file(tmp_path):
    skill = make_skill(tmp_path, refs={"fix-loop.md": 1})
    (skill / "references" / "fix-loop.md").write_text("opus\n")
    assert check_skill.check_opus(skill) == []


def test_opus_allowed_in_secure_skill(tmp_path):
    skill = make_skill(tmp_path, body_text="Use opus here.\n")
    skill = skill.rename(tmp_path / "secure")
    assert check_skill.check_opus(skill) == []


@pytest.mark.parametrize("evals", [0, 1])
def test_too_few_evals_flagged(tmp_path, evals):
    skill = make_skill(tmp_path, evals=evals)
    assert check_skill.check_evals(skill) == [f"demo: {evals} eval cases under evals/ (min 2)"]


def test_results_dir_is_not_an_eval_case(tmp_path):
    skill = make_skill(tmp_path, evals=1)
    (skill / "evals" / "results").mkdir()
    (skill / "evals" / "results" / "prompt.md").write_text("p")
    assert len(check_skill.eval_cases(skill)) == 1
