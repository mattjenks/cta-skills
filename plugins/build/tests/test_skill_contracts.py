"""Text contracts for the front-of-loop skills: the phrases and behaviors that must exist."""

import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "skills"


def text(skill: str) -> str:
    """SKILL.md plus its references, the whole instruction text of one skill."""
    root = SKILLS / skill
    parts = [(root / "SKILL.md").read_text()]
    parts += [p.read_text() for p in sorted((root / "references").glob("*.md"))]
    return "\n".join(parts)


def has(skill: str, *patterns: str) -> None:
    body = text(skill)
    for pattern in patterns:
        assert re.search(pattern, body, re.I | re.S), f"{skill}: missing /{pattern}/"


@pytest.mark.parametrize("skill", ["prime", "design", "plan"])
def test_skill_exists_with_matching_name(skill):
    head = (SKILLS / skill / "SKILL.md").read_text().split("---")[1]
    assert re.search(rf"^name: {skill}$", head, re.M)


@pytest.mark.parametrize("skill", ["prime", "design", "plan"])
def test_no_fable_and_no_persona(skill):
    body = text(skill)
    assert not re.search(r"\bfable\b", body, re.I)
    assert not re.search(r"\bjax\b", body, re.I)


# --- prime ---


def test_prime_scope_argument_and_sources():
    has("prime", r"backend", r"frontend", r"README", r"manifest", r"git log")


def test_prime_writes_nothing():
    has("prime", r"writes nothing|read-only|do not write")


# --- design ---


def test_design_resolves_the_knowledge_base():
    has(
        "design",
        r"/core:init-kb",
        r"record_project|kbwork\.py project",
        r"open_build|kbwork\.py open",
        r"write_pointer|--repo",
        r"unmapped|not mapped",
    )


def test_design_paths_in_the_knowledge_base():
    has("design", r"<projects_dir>/<slug>/<topic>-design\.md", r"worktree")


def test_design_stop_and_classification():
    has(
        "design",
        r"STOP",
        r"approves? the design",
        r"Small: plan review skipped",
        r"5 files or fewer",
        r"no new production dependency",
        r"auth, secrets, hooks or CI",
        r"override",
    )


def test_design_commits_and_pushes_the_worktree_after_approval():
    has("design", r"commit", r"push", r"after (Matt|the owner) approves|after approval")
    has("design", r"never (push|check out)[^.]*(main|default)|never push to")


def test_design_builder_check_names_sonnet_and_models():
    has("design", r"builder check", r"sonnet", r"\.\./implement/references/models\.md")
    assert (SKILLS / "design/references/builder-check.md").is_file()


def test_design_credits_superpowers():
    assert "Adapted from obra/superpowers" in (SKILLS / "design/SKILL.md").read_text()


# --- plan ---


def test_plan_normal_only():
    has("plan", r"small", r"implement", r"skip")


def test_plan_writes_plan_md_in_project_folder():
    has("plan", r"<projects_dir>/<slug>/plan\.md", r"plan-format\.md")


def test_plan_format_has_required_sections():
    fmt = (SKILLS / "plan/references/plan-format.md").read_text()
    for needle in ("Global Constraints", "Review Focus", "Files:", "Interfaces", "failing test"):
        assert needle in fmt, needle
    assert re.search(r"five|5 ", fmt, re.I)


def test_plan_stops():
    has(
        "plan",
        r"STOP",
        r"approves? the plan",
        r"new production dependency",
        r"name",
        r"version",
        r"license",
        r"reason",
    )


def test_plan_credits_both_sources():
    body = (SKILLS / "plan/SKILL.md").read_text() + (SKILLS / "plan/references/plan-format.md").read_text()
    assert "Adapted from obra/superpowers" in body
    assert "Adapted from coleam00/skills" in body


def test_plan_dispatches_name_sonnet_if_any():
    body = text("plan")
    if re.search(r"subagent|dispatch", body, re.I):
        assert re.search(r"sonnet", body, re.I)
        assert "models.md" in body
