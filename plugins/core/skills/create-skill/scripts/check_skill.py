#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Check skill folders against the authoring budgets.

Usage: uv run --script check_skill.py <skill-dir> [<skill-dir> ...]

Each argument is a folder holding a SKILL.md. Exits 1 and prints one line per
problem when any check fails. tests/test_skill_budgets.py imports this module,
so the checks run the same way in the suite and on a skill outside this repo.
"""

import re
import sys
from pathlib import Path

DESCRIPTION_MAX = 400
BODY_MAX = 150
REFERENCE_MAX = 300
EVALS_MIN = 2
MODEL_NAMES = ("haiku", "sonnet", "opus")
# Skills (by directory name) and files (by name) where the most capable model is allowed.
OPUS_SKILLS = {"secure", "review"}
OPUS_FILES = {"models.md", "fix-loop.md"}
RESERVED_EVAL_DIRS = {"results", "mocks", "node_modules", "files"}
DISPATCH = re.compile(
    r"\b(?:dispatch\w*|spawn\w*)\b[^.\n]*\bagents?\b|\bsubagents?\b", re.I
)


def description(skill_md: Path) -> str:
    """The frontmatter description, with folded or quoted YAML flattened."""
    text = skill_md.read_text()
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    if not match:
        return ""
    lines = match.group(1).splitlines()
    for i, line in enumerate(lines):
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            if value in (">", "|", ">-", "|-"):
                block = []
                for nxt in lines[i + 1 :]:
                    if not nxt.startswith((" ", "\t")):
                        break
                    block.append(nxt.strip())
                return " ".join(block)
            return value.strip("\"'")
    return ""


def references(skill: Path) -> list[Path]:
    return sorted((skill / "references").glob("*.md"))


def skill_files(skill: Path) -> list[Path]:
    return [skill / "SKILL.md", *references(skill)]


def eval_cases(skill: Path) -> list[Path]:
    root = skill / "evals"
    if not root.is_dir():
        return []
    return sorted(
        d
        for d in root.iterdir()
        if d.is_dir()
        and d.name not in RESERVED_EVAL_DIRS
        and ((d / "prompt.md").exists() or (d / "case.yaml").exists())
    )


def check_description(skill: Path) -> list[str]:
    n = len(description(skill / "SKILL.md"))
    if n == 0 or n > DESCRIPTION_MAX:
        return [f"{skill.name}: description is {n} characters (1 to {DESCRIPTION_MAX})"]
    return []


def check_body(skill: Path) -> list[str]:
    n = len((skill / "SKILL.md").read_text().splitlines())
    return [f"{skill.name}: SKILL.md is {n} lines (max {BODY_MAX})"] if n > BODY_MAX else []


def check_references(skill: Path) -> list[str]:
    out = []
    for ref in references(skill):
        n = len(ref.read_text().splitlines())
        if n > REFERENCE_MAX:
            out.append(f"{skill.name}: references/{ref.name} is {n} lines (max {REFERENCE_MAX})")
    return out


def check_linked(skill: Path) -> list[str]:
    body = (skill / "SKILL.md").read_text()
    return [
        f"{skill.name}: references/{ref.name} is not named in SKILL.md"
        for ref in references(skill)
        if ref.name not in body
    ]


def check_models(skill: Path) -> list[str]:
    text = "\n".join(f.read_text() for f in skill_files(skill))
    if not DISPATCH.search(text):
        return []
    out = []
    if not any(re.search(rf"\b{m}\b", text, re.I) for m in MODEL_NAMES):
        out.append(f"{skill.name}: dispatches a subagent without naming haiku, sonnet or opus")
    if "models.md" not in text:
        out.append(f"{skill.name}: dispatches a subagent without linking models.md")
    return out


def check_opus(skill: Path) -> list[str]:
    if skill.name in OPUS_SKILLS:
        return []
    return [
        f"{skill.name}: '{f.name}' mentions opus outside the allowed roles"
        for f in skill_files(skill)
        if f.name not in OPUS_FILES and re.search(r"\bopus\b", f.read_text(), re.I)
    ]


def check_fable(skill: Path) -> list[str]:
    """Fable is never a dispatch model; only models.md may mention it (to say so)."""
    return [
        f"{skill.name}: '{f.name}' names fable as a model"
        for f in skill_files(skill)
        if f.name != "models.md" and re.search(r"\bfable\b", f.read_text(), re.I)
    ]


def check_evals(skill: Path) -> list[str]:
    n = len(eval_cases(skill))
    return [f"{skill.name}: {n} eval cases under evals/ (min {EVALS_MIN})"] if n < EVALS_MIN else []


CHECKS = (
    check_description,
    check_body,
    check_references,
    check_linked,
    check_models,
    check_opus,
    check_fable,
    check_evals,
)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    problems: list[str] = []
    for arg in argv:
        skill = Path(arg)
        if not (skill / "SKILL.md").is_file():
            problems.append(f"{arg}: no SKILL.md")
            continue
        for check in CHECKS:
            problems.extend(check(skill))
    for line in problems:
        print(line)
    if not problems:
        print(f"ok: {len(argv)} skill(s) within budget")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
