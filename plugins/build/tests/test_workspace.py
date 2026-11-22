import subprocess
import sys
from pathlib import Path

import pytest

import workspace

GIT = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.invalid"]
SCRIPT = Path(workspace.__file__)


def git(cwd, *args):
    return subprocess.run(
        [*GIT, "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "init")
    return path


def test_workspace_marker_and_collision(tmp_path):
    repo = make_repo(tmp_path / "repo")
    (repo / "alpha").mkdir()
    (repo / "beta").mkdir()
    (repo / "gamma").mkdir()
    plans = [repo / d / "plan.md" for d in ("alpha", "beta", "gamma")]
    for p in plans:
        p.write_text("# plan\n")
    first = workspace.workspace_dir(repo, plans[0])
    assert first == (repo / ".cta/sdd/plan").resolve()
    assert (first / "plan-path").read_text().strip() == "alpha/plan.md"
    # same plan again resolves to the same directory
    assert workspace.workspace_dir(repo, plans[0]) == first
    # different plan, same slug: disambiguated by parent dir name
    second = workspace.workspace_dir(repo, plans[1])
    assert second.name == "plan-beta"
    assert (second / "plan-path").read_text().strip() == "beta/plan.md"
    # a third plan whose parent-name slug is taken gets a counter
    (repo / ".cta/sdd/plan-gamma").mkdir()
    (repo / ".cta/sdd/plan-gamma/plan-path").write_text("other/plan.md\n")
    third = workspace.workspace_dir(repo, plans[2])
    assert third.name == "plan-gamma-2"
    # self-ignoring gitignore, and .cta/ excluded: nothing shows in status
    assert (repo / ".cta/sdd/.gitignore").read_text() == "*\n"
    assert ".cta" not in git(repo, "status", "--porcelain")
    # outside-repo plans record an absolute path
    outside = tmp_path / "elsewhere" / "other.md"
    outside.parent.mkdir()
    outside.write_text("x\n")
    ws = workspace.workspace_dir(repo, outside)
    assert (ws / "plan-path").read_text().strip() == str(outside.resolve())


PLAN = """# Plan

### Task 1: First

one body

### Task 10b: Tenth b

ten b body
```
### Task 99: inside fence
```
#### Task 10b.1: sub

sub body

### Task 10: Ten

ten body
### Task 11: Eleven
"""


def test_task_brief_extracts_10b(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN)
    out = workspace.task_brief(plan, "10b", tmp_path / "out")
    assert out.name == "task-10b-brief.md"
    text = out.read_text()
    assert text.startswith("### Task 10b: Tenth b")
    assert "ten b body" in text and "inside fence" in text and "sub body" in text
    assert "ten body" not in text and "one body" not in text
    ten = workspace.task_brief(plan, "10", tmp_path / "out").read_text()
    assert ten.startswith("### Task 10: Ten") and "Eleven" not in ten
    with pytest.raises(workspace.WorkspaceError):
        workspace.task_brief(plan, "7", tmp_path / "out")


def test_review_package_multi_commit(tmp_path):
    repo = make_repo(tmp_path / "repo")
    base = git(repo, "rev-parse", "HEAD").strip()
    for i in (1, 2, 3):
        (repo / f"f{i}.txt").write_text(f"line {i}\n")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", f"change {i}")
    head = git(repo, "rev-parse", "HEAD").strip()
    out = workspace.review_package(repo, base, head, tmp_path / "out")
    assert out.name == f"review-{base[:7]}..{head[:7]}.diff"
    text = out.read_text()
    for i in (1, 2, 3):
        assert f"change {i}" in text and f"f{i}.txt" in text
    assert text.index("change 1") < text.index("f1.txt |") < text.index("diff --git")
    with pytest.raises(workspace.WorkspaceError):
        workspace.review_package(repo, head, base, tmp_path / "out")
    with pytest.raises(workspace.WorkspaceError):
        workspace.review_package(repo, head, head, tmp_path / "out")


def test_cli_prints_paths(tmp_path):
    repo = make_repo(tmp_path / "repo")
    plan = repo / "plan.md"
    plan.write_text(PLAN)
    run = lambda *a: subprocess.run(
        [sys.executable, str(SCRIPT), *a], capture_output=True, text=True, cwd=repo
    )
    ws = run("workspace", str(plan))
    assert ws.returncode == 0 and ws.stdout.strip().endswith(".cta/sdd/plan")
    br = run("brief", str(plan), "1")
    assert br.returncode == 0 and br.stdout.strip().endswith("task-1-brief.md")
    bad = run("brief", str(plan), "42")
    assert bad.returncode != 0 and "42" in bad.stderr


def test_security_toml_stays_visible(tmp_path):
    import kbwork

    repo = make_repo(tmp_path / "repo")
    plan = repo / "plan.md"
    plan.write_text(PLAN)
    build = kbwork.Build("app", "t", __import__("datetime").date(2026, 1, 2), tmp_path / "w", "b", tmp_path / "f")
    kbwork.write_pointer(repo, build)
    workspace.workspace_dir(repo, plan)
    (repo / ".cta/security.toml").write_text("gated = true\n")
    status = git(repo, "status", "--porcelain", "-uall")
    assert ".cta/security.toml" in status
    assert "active-build" not in status and "sdd" not in status


def test_brief_last_task_to_eof_and_spaces(tmp_path):
    d = tmp_path / "my plans"
    d.mkdir()
    plan = d / "my plan.md"
    plan.write_text("### Task 1: A\n\na\n\n### Task 2: B\n\nlast line still b\nend", encoding="utf-8")
    out = workspace.task_brief(plan, "2", tmp_path / "o")
    assert out.read_text(encoding="utf-8").endswith("last line still b\nend\n")


def test_brief_unclosed_fence_refused(tmp_path):
    plan = tmp_path / "p.md"
    plan.write_text("### Task 1: A\n\n```\ncode\n### Task 2: hidden\n")
    with pytest.raises(workspace.WorkspaceError, match="never closes"):
        workspace.task_brief(plan, "1", tmp_path / "o")


def test_slug_strips_only_md(tmp_path):
    repo = make_repo(tmp_path / "repo")
    plan = repo / "plan.v2.txt"
    plan.write_text("x\n")
    assert workspace.workspace_dir(repo, plan).name == "plan.v2.txt"
