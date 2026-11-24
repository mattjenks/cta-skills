"""Text contracts for the learn skills: the phrases and behaviors that must exist."""

import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "skills"
ALL_SKILLS = ["report", "decide", "deliver"]


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


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_skill_exists_with_matching_name(skill):
    head = (SKILLS / skill / "SKILL.md").read_text().split("---")[1]
    assert re.search(rf"^name: {skill}$", head, re.M)


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_no_fable_and_no_persona(skill):
    body = text(skill)
    assert not re.search(r"\bfable\b", body, re.I)
    assert not re.search(r"\bjax\b", body, re.I)


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_no_personal_value(skill):
    body = re.sub(r"\$\{[^}]*\}", "", text(skill))
    assert "@" not in body
    assert not re.search(r"/(Users|home)/\w", body)


# --- report ---


def test_report_description_names_the_weekly_report():
    head = (SKILLS / "report" / "SKILL.md").read_text().split("---")[1]
    assert re.search(r"^description:.*weekly report", head, re.M | re.I)


def test_report_runs_draft_then_render():
    has("report", r"report\.py\W+draft\W+--end", r"report\.py\W+render\W+--date")
    body = text("report")
    assert body.index("report.py draft") < body.index("report.py render")


def test_report_prints_the_report_line_last():
    has("report", r"REPORT: <path", r"last line")


def test_report_prose_rules():
    has("report", r"problem.*why.*change.*measure", r"evidence", r"never a function",
        r"one or two sentences", r"no prompt text|never quote")


def test_report_treats_content_as_data():
    has("report", r"data,? never instructions")


def test_report_commits_on_a_branch_in_a_worktree():
    has("report", r"learn/report-<date>", r"git worktree add", r"live checkout",
        r"index\.json", r"gh pr create", r"no remote|without a remote")


# --- decide ---


def test_decide_description_names_the_decision():
    head = (SKILLS / "decide" / "SKILL.md").read_text().split("---")[1]
    assert re.search(r"^description:.*(accept|reject|decision)", head, re.M | re.I)


def test_decide_runs_the_script_and_shows_the_row():
    has("decide", r"decide\.py", r"accept\|defer\|reject|accept, defer or reject",
        r"show.*row|row.*show")


def test_decide_passes_the_reason_only_on_stdin():
    has("decide", r"--reason-stdin", r"<<'CTA_REASON'", r"never.*(argument|command line)")


def test_decide_asks_for_a_reason_on_reject():
    has("decide", r"reject.*(no|without|missing).*reason.*ask|ask.*reason")


def test_decide_exit_codes_and_idempotence():
    has("decide", r"exit 2", r"exit 3", r"exit 4", r"already|existing")


def test_decide_treats_content_as_data():
    has("decide", r"data,? never instructions")


# --- deliver ---


def test_deliver_description_names_the_email():
    head = (SKILLS / "deliver" / "SKILL.md").read_text().split("---")[1]
    assert re.search(r"^description:.*(email|deliver)", head, re.M | re.I)


def test_deliver_prepares_then_sends_then_records():
    has("deliver", r"deliver\.py\W+prepare\W+--date", r"deliver\.py\W+record\W+--date")
    body = text("deliver")
    prepare = re.search(r"deliver\.py\W+prepare", body).start()
    assert prepare < body.index("--result sent")


def test_deliver_uses_only_the_prepared_recipient():
    has("deliver", r"only the `?to`? from `?prepare`?", r"compare.*recipient.*`?to`?.*before",
        r"no cc|never.*(cc|bcc)", r"never.*address.*(report|content)")


def test_deliver_falls_back_to_a_notification():
    has("deliver", r"deliver\.py\W+notify", r"--result fallback", r"no .*(tool|way).*send")


def test_deliver_treats_content_as_data():
    has("deliver", r"data,? never instructions")


def test_deliver_record_commits_the_record_on_the_report_branch():
    has("deliver", r"record.*commit", r"learn/report-", r"never the default branch")


def test_deliver_exit_codes():
    has("deliver", r"exit 2")


def test_deliver_has_two_evals():
    cases = [p for p in (SKILLS / "deliver" / "evals").iterdir() if (p / "case.yaml").is_file()]
    assert len(cases) >= 2
