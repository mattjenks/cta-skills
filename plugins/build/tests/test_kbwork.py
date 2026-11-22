import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

import kbwork
from kbwork import KbError

TODAY = date(2026, 1, 2)
GIT = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.invalid"]


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


@pytest.fixture
def kb(tmp_path):
    return make_repo(tmp_path / "kb")


def test_record_project_appends_without_rewriting(tmp_path):
    cfg = tmp_path / "config.toml"
    original = '# my config\nkb = "~/kb"\n\n[notify]\nmin_turn_seconds = 5\n'
    cfg.write_text(original)
    repo = tmp_path / "repo"
    repo.mkdir()
    kbwork.record_project(cfg, repo, "app")
    text = cfg.read_text()
    assert text.startswith(original)
    assert "[projects]" in text
    assert f'"{repo.resolve()}" = "app"' in text
    other = tmp_path / "other"
    other.mkdir()
    kbwork.record_project(cfg, other, "other-app")
    text2 = cfg.read_text()
    assert text2.startswith(text)
    assert text2.count("[projects]") == 1
    import tomllib

    assert tomllib.loads(text2)["projects"] == {
        str(repo.resolve()): "app",
        str(other.resolve()): "other-app",
    }


def test_record_project_creates_missing_file(tmp_path):
    cfg = tmp_path / "sub" / "config.toml"
    repo = tmp_path / "repo"
    repo.mkdir()
    kbwork.record_project(cfg, repo, "app")
    assert "[projects]" in cfg.read_text()


@pytest.mark.parametrize("slug", ["Bad", "-x", "a b", "", "a" * 64, "a/b"])
def test_record_project_rejects_bad_slug(tmp_path, slug):
    cfg = tmp_path / "config.toml"
    with pytest.raises(ValueError):
        kbwork.record_project(cfg, tmp_path, slug)
    assert not cfg.exists()


def test_open_build_creates_worktree_on_new_branch(tmp_path, kb):
    root = tmp_path / "wt"
    b = kbwork.open_build(kb, "projects", "app", "login", TODAY, root)
    assert b.worktree == root / "app-2026-01-02-login"
    assert b.branch == "build/app-2026-01-02-login"
    assert b.folder == b.worktree / "projects/app/builds/2026-01-02-login"
    assert b.folder.is_dir()
    assert git(b.worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() == b.branch
    assert git(b.worktree, "rev-parse", "HEAD") == git(kb, "rev-parse", "main")


def test_open_build_bad_topic(tmp_path, kb):
    with pytest.raises(ValueError):
        kbwork.open_build(kb, "projects", "app", "Bad Topic", TODAY, tmp_path / "wt")


def test_open_build_reuses_existing(tmp_path, kb):
    root = tmp_path / "wt"
    first = kbwork.open_build(kb, "projects", "app", "login", TODAY, root)
    (first.folder / "note.md").write_text("x")
    second = kbwork.open_build(kb, "projects", "app", "login", TODAY, root)
    assert second == first
    assert (second.folder / "note.md").read_text() == "x"


def test_open_build_uses_origin_default_branch(tmp_path):
    origin = make_repo(tmp_path / "origin")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(bare)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    # remote gains a commit the clone has not fetched
    (origin / "new.md").write_text("n")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "more")
    git(origin, "push", "-q", str(bare), "main")
    b = kbwork.open_build(clone, "projects", "app", "t", TODAY, tmp_path / "wt")
    assert (b.worktree / "new.md").exists()


def test_live_kb_untouched(tmp_path, kb):
    git(kb, "checkout", "-q", "-b", "side")
    (kb / "README.md").write_text("dirty\n")
    (kb / "untracked.md").write_text("u\n")
    before = (
        git(kb, "rev-parse", "HEAD"),
        git(kb, "rev-parse", "--abbrev-ref", "HEAD"),
        git(kb, "status", "--porcelain"),
    )
    b = kbwork.open_build(kb, "projects", "app", "login", TODAY, tmp_path / "wt")
    (b.folder / "design.md").write_text("d")
    git(b.worktree, "add", ".")
    git(b.worktree, "commit", "-q", "-m", "doc")
    after = (
        git(kb, "rev-parse", "HEAD"),
        git(kb, "rev-parse", "--abbrev-ref", "HEAD"),
        git(kb, "status", "--porcelain"),
    )
    assert before == after
    assert (kb / "README.md").read_text() == "dirty\n"
    assert not (kb / "projects").exists()


def test_not_git_raises_kberror(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(KbError) as exc:
        kbwork.open_build(plain, "projects", "app", "t", TODAY, tmp_path / "wt")
    assert str(exc.value) == f"knowledge base at {plain} is not a git repo; run /core:init-kb"


def test_pointer_roundtrip_and_exclude_once(tmp_path, kb):
    repo = make_repo(tmp_path / "repo")
    assert kbwork.read_pointer(repo) is None
    b = kbwork.open_build(kb, "projects", "app", "login", TODAY, tmp_path / "wt")
    p = kbwork.write_pointer(repo, b)
    assert p == repo / ".cta/active-build"
    data = json.loads(p.read_text())
    assert set(data) == {"worktree", "folder", "slug", "topic", "branch"}
    kbwork.write_pointer(repo, b)
    exclude = (repo / ".git/info/exclude").read_text()
    assert exclude.splitlines().count(".cta/") == 1
    assert git(repo, "status", "--porcelain") == ""
    got = kbwork.read_pointer(repo)
    assert got.worktree == b.worktree and got.folder == b.folder
    assert got.slug == "app" and got.topic == "login" and got.branch == b.branch
    assert got.date == TODAY
    kbwork.clear_pointer(repo)
    assert kbwork.read_pointer(repo) is None
    kbwork.clear_pointer(repo)  # idempotent


def test_read_pointer_corrupt_is_none(tmp_path):
    repo = make_repo(tmp_path / "repo")
    (repo / ".cta").mkdir()
    (repo / ".cta/active-build").write_text("{nope")
    assert kbwork.read_pointer(repo) is None


def test_close_build_keeps_unmerged(tmp_path, kb, capsys):
    b = kbwork.open_build(kb, "projects", "app", "login", TODAY, tmp_path / "wt")
    (b.folder / "design.md").write_text("d")
    git(b.worktree, "add", ".")
    git(b.worktree, "commit", "-q", "-m", "doc")
    msg = kbwork.close_build(b)
    assert b.worktree.exists()
    assert "not merged" in msg


def test_close_build_removes_merged(tmp_path, kb):
    b = kbwork.open_build(kb, "projects", "app", "login", TODAY, tmp_path / "wt")
    # branch has no commits beyond main: merged
    msg = kbwork.close_build(b)
    assert not b.worktree.exists()
    assert "removed" in msg
