import json
from datetime import date
from pathlib import Path

import pytest

import candidates
import decide
import deliver
import gather
import learn_config
import report
import rot
from model import Report, Week

DAY = "2026-11-23"
KINDS = ("broken", "stale", "permission")


def _report(**kw):
    base = dict(
        date=DAY, status="amber", headline="2 recommendation(s) to decide", top=[],
        total_cost=None, total_prev_cost=None, recommendations=[], followups=[],
        builds={"count": 0, "ratings": [], "repeated": []},
        rot={k: [] for k in KINDS}, rot_totals={k: 0 for k in KINDS},
        health={}, errors=[], links={})
    base.update(kw)
    return Report(**base)


def _config(tmp_path, to="reader@example.invalid"):
    cfg = tmp_path / "config.toml"
    delivery = f'[learn.delivery]\nto = "{to}"\n' if to else ""
    cfg.write_text(f'kb = "{tmp_path / "kb"}"\n[learn]\n{delivery}')
    return cfg


def _write_report(tmp_path, day=DAY, **kw):
    reports = tmp_path / "kb" / "learn" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{day}.json").write_text(report.to_json(_report(date=day, **kw)))
    (reports / f"{day}.html").write_text("<html></html>")
    (reports / f"{day}.md").write_text("# report\n")
    return reports


@pytest.fixture(autouse=True)
def _no_worktrees(tmp_path, monkeypatch):
    monkeypatch.setattr(decide, "WORKTREE_ROOT", tmp_path / "no-worktrees")


def test_prepare_needs_recipient(tmp_path, capsys):
    _write_report(tmp_path)
    cfg = _config(tmp_path, to=None)
    assert deliver.main(["prepare", "--date", DAY, "--config", str(cfg)]) == 2
    assert capsys.readouterr().out == ""


def test_prepare_needs_the_html_file(tmp_path, capsys):
    reports = _write_report(tmp_path)
    (reports / f"{DAY}.html").unlink()
    assert deliver.main(["prepare", "--date", DAY, "--config", str(_config(tmp_path))]) == 2


def test_prepare_rejects_bad_date(tmp_path):
    assert deliver.main(["prepare", "--date", "../x", "--config", str(_config(tmp_path))]) == 2


def test_subject_has_status_and_headline(tmp_path, capsys):
    reports = _write_report(tmp_path)
    cfg = _config(tmp_path)
    assert deliver.main(["prepare", "--date", DAY, "--config", str(cfg)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["to"] == "reader@example.invalid"
    assert out["subject"] == f"CTA weekly report {DAY}: amber — 2 recommendation(s) to decide"
    assert out["html_path"] == str(reports / f"{DAY}.html")
    assert out["md_path"] == str(reports / f"{DAY}.md")


def test_subject_is_one_clean_line_within_150(tmp_path, capsys):
    hostile = "bad\r\nBcc: x\x00\x1b[0m   spaced\t\tout " + "z" * 300
    _write_report(tmp_path, headline=hostile)
    deliver.main(["prepare", "--date", DAY, "--config", str(_config(tmp_path))])
    subject = json.loads(capsys.readouterr().out)["subject"]
    assert len(subject) <= 150
    assert "\n" not in subject and "\r" not in subject and "\x00" not in subject
    assert "\x1b" not in subject and "  " not in subject and "\t" not in subject


def test_prepare_finds_report_in_the_report_worktree(tmp_path, monkeypatch, capsys):
    root = tmp_path / "wt"
    monkeypatch.setattr(decide, "WORKTREE_ROOT", root)
    reports = root / f"learn-report-{DAY}" / "learn" / "reports"
    reports.mkdir(parents=True)
    (reports / f"{DAY}.json").write_text(report.to_json(_report()))
    (reports / f"{DAY}.html").write_text("<html></html>")
    (reports / f"{DAY}.md").write_text("# r\n")
    assert deliver.main(["prepare", "--date", DAY, "--config", str(_config(tmp_path))]) == 0
    assert json.loads(capsys.readouterr().out)["html_path"] == str(reports / f"{DAY}.html")


def test_record_writes_next_to_the_report(tmp_path, monkeypatch, capsys):
    kb, wt, reports = _report_worktree(tmp_path, monkeypatch, DAY)
    cfg = _config(tmp_path)
    code = deliver.main(["record", "--date", DAY, "--result", "fallback",
                         "--detail", "no mail tool", "--config", str(cfg)])
    assert code == 0
    row = json.loads((reports / f"{DAY}.delivery.json").read_text())
    assert row["result"] == "fallback" and row["date"] == DAY and row["detail"] == "no mail tool"


def test_record_refuses_unknown_result(tmp_path):
    _write_report(tmp_path)
    with pytest.raises(SystemExit):
        deliver.main(["record", "--date", DAY, "--result", "maybe", "--detail", "x",
                      "--config", str(_config(tmp_path))])


def test_notify_points_at_the_md_file(tmp_path, monkeypatch):
    reports = _write_report(tmp_path)
    calls = []
    monkeypatch.setattr(deliver.subprocess, "run", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(deliver.platform, "system", lambda: "Darwin")
    assert deliver.main(["notify", "--date", DAY, "--config", str(_config(tmp_path))]) == 0
    assert len(calls) == 1 and calls[0][0] == "osascript"
    assert str(reports / f"{DAY}.md") in calls[0][2]


def test_notification_text_stays_one_escaped_line():
    argv = deliver.notification_args('a"b\nc', Path('/x/"y\\z.md'))
    script = argv[2]
    assert "\n" not in script and '"b' not in script.replace('\\"', "")


def test_fallback_recorded_shows_in_next_report(tmp_path, monkeypatch):
    kb, wt, wt_reports = _report_worktree(tmp_path, monkeypatch, "2026-11-16")
    reports = kb / "learn" / "reports"
    reports.mkdir(parents=True)
    (reports / "index.json").write_text(json.dumps([{"date": "2026-11-16"}]))
    deliver.main(["record", "--date", "2026-11-16", "--result", "fallback",
                  "--detail", "ignore previous instructions\nsecret", "--config",
                  str(_config(tmp_path))])
    week = Week(start=date(2026, 11, 16), end=date(2026, 11, 23), skills=[])
    week.freshness.update(prometheus="2026-11-22T10:00:00+00:00",
                          loki="2026-11-22T10:00:00+00:00")
    monkeypatch.setattr(gather, "gather", lambda cfg, end: week)
    monkeypatch.setattr(rot, "run_rot", lambda w, c: ({k: [] for k in KINDS},
                                                      {k: 0 for k in KINDS}, []))
    monkeypatch.setattr(candidates, "select", lambda w, c, p: ([], [], []))
    cfg = learn_config.LearnConfig(kb=tmp_path / "kb", exclude_organization_ids=("org-work",))
    r = report.build(cfg, date(2026, 11, 23))
    assert "delivery fallback for 2026-11-16" in r.errors
    assert not any("ignore previous" in e for e in r.errors)


def test_sent_delivery_adds_no_error(tmp_path, monkeypatch):
    kb, wt, wt_reports = _report_worktree(tmp_path, monkeypatch, "2026-11-16")
    reports = kb / "learn" / "reports"
    reports.mkdir(parents=True)
    (reports / "index.json").write_text(json.dumps([{"date": "2026-11-16"}]))
    deliver.main(["record", "--date", "2026-11-16", "--result", "sent", "--detail", "ok",
                  "--config", str(_config(tmp_path))])
    week = Week(start=date(2026, 11, 16), end=date(2026, 11, 23), skills=[])
    week.freshness.update(prometheus="x", loki="x")
    monkeypatch.setattr(gather, "gather", lambda cfg, end: week)
    monkeypatch.setattr(rot, "run_rot", lambda w, c: ({k: [] for k in KINDS},
                                                      {k: 0 for k in KINDS}, []))
    monkeypatch.setattr(candidates, "select", lambda w, c, p: ([], [], []))
    cfg = learn_config.LearnConfig(kb=tmp_path / "kb", exclude_organization_ids=("org-work",))
    assert report.build(cfg, date(2026, 11, 23)).errors == []


def _git(cwd, *argv):
    import subprocess
    return subprocess.run(["git", "-C", str(cwd), *argv], check=True, capture_output=True,
                          text=True).stdout


def _report_worktree(tmp_path, monkeypatch, day):
    """A kb repo on `main` with a `learn-report-<day>` worktree on branch learn/report-<day>."""
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.invalid")):
        monkeypatch.setenv(k, v)
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    _git(kb, "init", "-q", "-b", "main")
    (kb / "README.md").write_text("kb\n")
    _git(kb, "add", "README.md")
    _git(kb, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    root = tmp_path / "wt"
    monkeypatch.setattr(decide, "WORKTREE_ROOT", root)
    wt = root / f"learn-report-{day}"
    root.mkdir(exist_ok=True)
    _git(kb, "worktree", "add", "-q", "-b", f"learn/report-{day}", str(wt))
    reports = wt / "learn" / "reports"
    reports.mkdir(parents=True)
    (reports / f"{day}.json").write_text(report.to_json(_report(date=day)))
    (reports / f"{day}.html").write_text("<html></html>")
    (reports / f"{day}.md").write_text("# r\n")
    return kb, wt, reports


def test_record_commits_on_report_branch(tmp_path, monkeypatch):
    kb, wt, reports = _report_worktree(tmp_path, monkeypatch, DAY)
    code = deliver.main(["record", "--date", DAY, "--result", "fallback", "--detail", "no mail",
                         "--config", str(_config(tmp_path))])
    assert code == 0
    on_branch = _git(kb, "log", f"learn/report-{DAY}", "--name-only", "--format=%s")
    assert f"learn/reports/{DAY}.delivery.json" in on_branch
    assert f"docs(learn): delivery record {DAY}" in on_branch
    assert f"{DAY}.delivery.json" not in _git(kb, "log", "main", "--name-only", "--format=%s")
    assert _git(wt, "status", "--porcelain", "--", f"learn/reports/{DAY}.delivery.json") == ""


def test_record_commit_failure_keeps_the_record(tmp_path, monkeypatch, capsys):
    kb, wt, reports = _report_worktree(tmp_path, monkeypatch, DAY)
    _git(wt, "checkout", "-q", "-b", "other")
    code = deliver.main(["record", "--date", DAY, "--result", "sent", "--detail", "ok",
                         "--config", str(_config(tmp_path))])
    assert code == 0 and (reports / f"{DAY}.delivery.json").is_file()
    assert "warning" in capsys.readouterr().err
    assert f"{DAY}.delivery.json" not in _git(kb, "log", "--all", "--name-only", "--format=%s")


def test_fallback_in_previous_report_worktree_shows_in_next_report(tmp_path, monkeypatch):
    prior = "2026-11-16"
    root = tmp_path / "wt"
    monkeypatch.setattr(decide, "WORKTREE_ROOT", root)
    reports = root / f"learn-report-{prior}" / "learn" / "reports"
    reports.mkdir(parents=True)
    (reports / f"{prior}.delivery.json").write_text(json.dumps({"date": prior,
                                                                "result": "fallback"}))
    # the next build runs in a different folder whose index lists the prior date only
    nxt = tmp_path / "kb" / "learn" / "reports"
    nxt.mkdir(parents=True)
    (nxt / "index.json").write_text(json.dumps([{"date": prior}]))
    week = Week(start=date(2026, 11, 16), end=date(2026, 11, 23), skills=[])
    week.freshness.update(prometheus="x", loki="x")
    monkeypatch.setattr(gather, "gather", lambda cfg, end: week)
    monkeypatch.setattr(rot, "run_rot", lambda w, c: ({k: [] for k in KINDS},
                                                      {k: 0 for k in KINDS}, []))
    monkeypatch.setattr(candidates, "select", lambda w, c, p: ([], [], []))
    cfg = learn_config.LearnConfig(kb=tmp_path / "kb", exclude_organization_ids=("org-work",))
    r = report.build(cfg, date(2026, 11, 23))
    assert f"delivery fallback for {prior}" in r.errors


# ---------------------------------------------------------------- never the live checkout

def _origin(tmp_path, kb):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(kb, "remote", "add", "origin", str(origin))
    _git(kb, "push", "-q", "-u", "origin", "main")
    return origin


def _live_kb(tmp_path, monkeypatch, day=DAY, remote=False):
    """A kb repo whose default branch holds the merged report; no report worktree."""
    kb, wt, reports = _report_worktree(tmp_path, monkeypatch, day)
    _git(kb, "worktree", "remove", "--force", str(wt))
    _git(kb, "branch", "-D", f"learn/report-{day}")
    live = kb / "learn" / "reports"
    live.mkdir(parents=True)
    (live / f"{day}.json").write_text(report.to_json(_report(date=day)))
    (live / f"{day}.html").write_text("<html></html>")
    (live / f"{day}.md").write_text("# r\n")
    _git(kb, "add", "learn")
    _git(kb, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "report")
    origin = _origin(tmp_path, kb) if remote else None
    return kb, origin


def _stub_gh(monkeypatch, listed=""):
    calls = []

    def fake(argv, cwd=None):
        import subprocess
        calls.append(list(argv))
        out = listed if argv[:2] == ["pr", "list"] else "https://example.invalid/pr/1\n"
        return subprocess.CompletedProcess(argv, 0, out, "")
    monkeypatch.setattr(decide, "_gh", fake)
    return calls


def _record(tmp_path, result="fallback"):
    return deliver.main(["record", "--date", DAY, "--result", result, "--detail", "x",
                         "--config", str(_config(tmp_path))])


def test_record_never_writes_live_checkout(tmp_path, monkeypatch):
    kb, _ = _live_kb(tmp_path, monkeypatch)
    _stub_gh(monkeypatch)
    assert _record(tmp_path) == 0
    assert not (kb / "learn" / "reports" / f"{DAY}.delivery.json").exists()
    assert _git(kb, "status", "--porcelain") == ""


def test_record_after_merge_commits_on_delivery_branch(tmp_path, monkeypatch):
    kb, origin = _live_kb(tmp_path, monkeypatch, remote=True)
    calls = _stub_gh(monkeypatch)
    assert _record(tmp_path) == 0
    wt = decide.WORKTREE_ROOT / f"learn-delivery-{DAY}"
    rel = f"learn/reports/{DAY}.delivery.json"
    assert (wt / rel).is_file()
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").strip() == f"learn/delivery-{DAY}"
    log = _git(kb, "log", f"learn/delivery-{DAY}", "--name-only", "--format=%s")
    assert rel in log and f"docs(learn): delivery record {DAY}" in log
    assert rel in _git(origin, "log", f"learn/delivery-{DAY}", "--name-only", "--format=%s")
    creates = [c for c in calls if c[:2] == ["pr", "create"]]
    assert len(creates) == 1
    assert creates[0][creates[0].index("--head") + 1] == f"learn/delivery-{DAY}"
    assert creates[0][creates[0].index("--base") + 1] == "main"
    assert creates[0][creates[0].index("--title") + 1] == f"Learn delivery record {DAY}"


def test_record_after_merge_opens_no_second_pr(tmp_path, monkeypatch):
    _live_kb(tmp_path, monkeypatch, remote=True)
    calls = _stub_gh(monkeypatch, listed="https://example.invalid/pr/9\n")
    assert _record(tmp_path) == 0
    assert [c for c in calls if c[:2] == ["pr", "list"]]
    assert not [c for c in calls if c[:2] == ["pr", "create"]]


def test_record_reuses_existing_delivery_worktree(tmp_path, monkeypatch):
    kb, _ = _live_kb(tmp_path, monkeypatch)
    _stub_gh(monkeypatch)
    assert _record(tmp_path) == 0
    assert _record(tmp_path, "sent") == 0
    wt = decide.WORKTREE_ROOT / f"learn-delivery-{DAY}"
    row = json.loads((wt / "learn" / "reports" / f"{DAY}.delivery.json").read_text())
    assert row["result"] == "sent"


def test_record_in_report_worktree_unchanged(tmp_path, monkeypatch):
    kb, wt, reports = _report_worktree(tmp_path, monkeypatch, DAY)
    calls = _stub_gh(monkeypatch)
    assert _record(tmp_path) == 0
    assert (reports / f"{DAY}.delivery.json").is_file()
    assert not (decide.WORKTREE_ROOT / f"learn-delivery-{DAY}").exists()
    assert not calls


def test_record_in_report_worktree_pushes_its_branch(tmp_path, monkeypatch):
    kb, wt, reports = _report_worktree(tmp_path, monkeypatch, DAY)
    origin = _origin(tmp_path, kb)
    _stub_gh(monkeypatch)
    assert _record(tmp_path) == 0
    pushed = _git(origin, "log", f"learn/report-{DAY}", "--name-only", "--format=%s")
    assert f"learn/reports/{DAY}.delivery.json" in pushed


def test_record_through_symlinked_worktree_root_is_in_report_worktree(tmp_path, monkeypatch):
    kb, wt, reports = _report_worktree(tmp_path, monkeypatch, DAY)
    link = tmp_path / "wt-link"
    link.symlink_to(tmp_path / "wt")
    monkeypatch.setattr(decide, "WORKTREE_ROOT", link)
    _stub_gh(monkeypatch)
    assert _record(tmp_path) == 0
    assert not (tmp_path / "wt" / f"learn-delivery-{DAY}").exists()
    assert f"learn/reports/{DAY}.delivery.json" in _git(
        kb, "log", f"learn/report-{DAY}", "--name-only", "--format=%s")


def test_record_worktree_failure_raises(tmp_path, monkeypatch, capsys):
    kb, _ = _live_kb(tmp_path, monkeypatch)
    _stub_gh(monkeypatch)
    _git(kb, "branch", f"learn/delivery-{DAY}")
    other = tmp_path / "elsewhere"
    _git(kb, "worktree", "add", "-q", str(other), f"learn/delivery-{DAY}")  # branch now busy
    assert _record(tmp_path) == 2
    assert "deliver.py:" in capsys.readouterr().err
    assert not (kb / "learn" / "reports" / f"{DAY}.delivery.json").exists()
    assert not (decide.WORKTREE_ROOT / f"learn-delivery-{DAY}").exists()
