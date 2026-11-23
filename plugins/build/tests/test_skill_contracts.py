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


DISPATCH = re.compile(r"(dispatch\w*|spawn\w*|use an?)\s[^.]*\bsubagent", re.I | re.S)


def undeclared_dispatches(body: str) -> list[str]:
    """Sentences that dispatch a subagent without naming a model and linking models.md."""
    bad = []
    for sentence in re.split(r"(?<=\.)\s+(?=[A-Z*])", body):
        if DISPATCH.search(sentence) and not (
            re.search(r"\b(haiku|sonnet|opus)\b", sentence, re.I) and "models.md" in sentence
        ):
            bad.append(" ".join(sentence.split()))
    return bad


@pytest.mark.parametrize("skill", ["prime", "design", "plan"])
def test_every_dispatch_names_its_model_and_links_models_md(skill):
    assert undeclared_dispatches((SKILLS / skill / "SKILL.md").read_text()) == []


def test_dispatch_check_fails_when_a_dispatch_names_no_model():
    fixture = (
        "Dispatch a fresh subagent on sonnet (model map: `../implement/references/models.md`) to check.\n\n"
        "Then dispatch a subagent to research the library.\n"
    )
    assert undeclared_dispatches(fixture) == ["Then dispatch a subagent to research the library."]


# --- approval status line ---


def test_design_writes_status_line_before_committing():
    body = (SKILLS / "design/SKILL.md").read_text()
    assert "Status: approved — Small" in body and "Status: approved — Normal" in body
    assert body.index("Status: approved") < body.index("docs(<slug>): design for <topic>")


def test_plan_reads_status_line_and_refuses_without_approval():
    pre = (SKILLS / "plan/SKILL.md").read_text().split("## 1.")[0]
    assert "Status: approved" in pre
    assert re.search(r"missing|absent|no `?Status", pre, re.I)
    assert re.search(r"refuse|stop", pre, re.I)
    assert re.search(r"Small[^\n]*/build:implement", pre, re.S)


def test_design_push_step_handles_no_remote_and_failure():
    step = (SKILLS / "design/SKILL.md").read_text().split("## 6.")[1]
    assert re.search(r"no (git )?remote", step, re.I)
    assert re.search(r"push fails|fails|failed", step, re.I)
    assert re.search(r"keep the commit", step, re.I)
