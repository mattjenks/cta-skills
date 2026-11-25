import io
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

import candidates
import decide
import gather
import learn_config
import report
from model import Candidate, Recommendation, Report, SkillUsage, Week

RID = "2026-11-23-R1"
FALLBACK = "fallback-org/fallback-repo"
SKILL_REPO = "acme/skills-a"

GH_STUB = """#!{python}
import json, os, sys
state = os.environ["GH_STATE"]
args = sys.argv[1:]
with open(os.path.join(state, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(args) + "\\n")
if args[:1] == ["api"]:
    print(os.environ.get("GH_PUSH", "true"))
elif args[:2] == ["issue", "create"]:
    n = sum(1 for line in open(os.path.join(state, "calls.jsonl")) if '"issue", "create"' in line)
    print(f"https://github.com/stub/stub/issues/{{n}}")
elif args[:2] == ["pr", "list"]:
    marker = os.path.join(state, "pr")
    if os.path.exists(marker):
        print("https://github.com/stub/kb/pull/1")
elif args[:2] == ["pr", "create"]:
    open(os.path.join(state, "pr"), "w").close()
    print("https://github.com/stub/kb/pull/1")
"""

# A stand-in scanner: writes an empty findings list to --report-path and exits 0.
GITLEAKS_STUB = """#!{python}
import json, sys
args = sys.argv[1:]
if "--report-path" in args:
    with open(args[args.index("--report-path") + 1], "w") as fh:
        json.dump([], fh)
"""


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                          text=True).stdout


def _report(skill="alpha", problem="cost grew"):
    cand = Candidate(skill=skill, signal="cost_growth", fingerprint=f"{skill}|cost_growth",
                     metric="cost_ratio", value=2.0, threshold=1.5, sessions=4,
                     evidence=["cost up"], panel="Cost by skill (USD, range)")
    rec = Recommendation(id=RID, candidate=cand, problem=problem, why="it adds up",
                         change="trim the prompt", measure="cost ratio under 1.5")
    usage = SkillUsage(skill=skill, plugin="plug", marketplace="market-a", invocations=7,
                       sessions=4, input_tokens=1000, output_tokens=500, cost_usd=3.0,
                       prev_cost_usd=2.0, prev_invocations=None)
    return Report(date="2026-11-23", status="green", headline="ok", top=[usage],
                  total_cost=None, total_prev_cost=None, recommendations=[rec], followups=[],
                  builds={"count": 0, "ratings": [], "repeated": []},
                  rot={k: [] for k in ("broken", "stale", "permission")},
                  rot_totals={k: 0 for k in ("broken", "stale", "permission")},
                  health={}, errors=[], links={})


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.kb = tmp_path / "kb"
        self.local = tmp_path / "local"
        self.state = tmp_path / "gh-state"
        self.state.mkdir()
        self.wt_root = tmp_path / "worktrees"
        self.events = []
        self.cfg = learn_config.LearnConfig(kb=self.kb, fallback_repo=FALLBACK,
                                            reports_dir=self.local)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        stub = bindir / "gh"
        stub.write_text(GH_STUB.format(python=sys.executable))
        stub.chmod(0o755)
        fake = tmp_path / "fake-gitleaks"
        fake.mkdir()
        scanner = fake / "gitleaks"
        scanner.write_text(GITLEAKS_STUB.format(python=sys.executable))
        scanner.chmod(0o755)
        self.base_path = os.environ["PATH"]
        self.bindir, self.fake_scanner_dir = bindir, fake
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(bindir), str(fake), self.base_path]))
        monkeypatch.setenv("GH_STATE", str(self.state))
        monkeypatch.setenv("GH_PUSH", "true")
        km = tmp_path / "known_marketplaces.json"
        km.write_text(json.dumps({"market-a": {"source": {"repo": SKILL_REPO}}}))
        monkeypatch.setattr(gather, "KNOWN_MARKETPLACES", km)
        monkeypatch.setattr(decide, "WORKTREE_ROOT", self.wt_root)
        monkeypatch.setattr(decide, "send", lambda event, endpoint: self.events.append(event))
        self.write_report(_report())

    def write_report(self, rep):
        self.kb.mkdir(exist_ok=True)
        if not (self.kb / ".git").exists():
            git(self.kb, "init", "-b", "main")
            git(self.kb, "config", "user.name", "Learn Test")
            git(self.kb, "config", "user.email", "learn-test@example.invalid")
            git(self.kb, "config", "commit.gpgsign", "false")
            git(self.kb, "commit", "--allow-empty", "-m", "init")
        reports = self.local / "reports"  # the configured reports_dir, never the knowledge base
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "2026-11-23.json").write_text(report.to_json(rep))

    def use_real_gitleaks(self, monkeypatch):
        monkeypatch.setenv("PATH", f"{self.bindir}{os.pathsep}{self.base_path}")

    def use_no_gitleaks(self, monkeypatch):
        dirs = [d for d in self.base_path.split(os.pathsep)
                if not (Path(d) / "gitleaks").exists()]
        monkeypatch.setenv("PATH", os.pathsep.join([str(self.bindir), *dirs]))

    @property
    def worktree(self):
        return self.wt_root / "learn-decisions"

    @property
    def decisions(self):
        return self.worktree / "learn" / "decisions.jsonl"

    def rows(self):
        if not self.decisions.exists():
            return []
        return [json.loads(line) for line in self.decisions.read_text().splitlines()]

    def gh_calls(self, *prefix):
        path = self.state / "calls.jsonl"
        if not path.exists():
            return []
        calls = [json.loads(line) for line in path.read_text().splitlines()]
        return [c for c in calls if c[:len(prefix)] == list(prefix)]

    def cli(self, monkeypatch, *argv, stdin=""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        cfg_path = self.tmp / "config.toml"
        cfg_path.write_text(f'kb = "{self.kb}"\n[learn]\nfallback_repo = "{FALLBACK}"\n'
                            f'reports_dir = "{self.local}"\n')
        return decide.main([*argv, "--config", str(cfg_path)])


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def test_accept_files_on_skill_repo_when_writable(env):
    row = decide.decide(env.cfg, RID, "accept", None)
    assert row["repo"] == SKILL_REPO
    assert row["issue_url"] == "https://github.com/stub/stub/issues/1"
    assert set(row) >= {"id", "date", "skill", "fingerprint", "decision", "reason", "repo",
                        "issue_url", "at"}
    (create,) = env.gh_calls("issue", "create")
    assert create[create.index("--repo") + 1] == SKILL_REPO
    assert create[create.index("--title") + 1] == f"alpha: cost_growth ({RID})"
    assert create[create.index("--label") + 1] == "cta-learn"
    assert "--body-file" in create
    assert env.gh_calls("label", "create")
    assert env.rows() == [row]
    assert git(env.worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() == "learn/decisions"
    assert RID in git(env.worktree, "log", "-1", "--format=%s")


def test_issue_body_has_the_fields_and_no_evidence(env):
    seen = {}
    real = decide._gh

    def spy(argv, **kw):
        if argv[:2] == ["issue", "create"]:
            seen["body"] = Path(argv[argv.index("--body-file") + 1]).read_text()
        return real(argv, **kw)

    decide._gh = spy
    try:
        decide.decide(env.cfg, RID, "accept", None)
    finally:
        decide._gh = real
    body = seen["body"]
    for part in ("cost grew", "it adds up", "trim the prompt", "cost ratio under 1.5",
                 "cost_ratio = 2.00", "2026-11-23"):
        assert part in body
    assert "cost up" not in body  # no evidence lines
    assert str(env.tmp) not in body


def test_accept_falls_back_when_not_writable(env, monkeypatch):
    monkeypatch.setenv("GH_PUSH", "false")
    row = decide.decide(env.cfg, RID, "accept", None)
    assert row["repo"] == FALLBACK
    assert SKILL_REPO in row["reason"] and "not writable" in row["reason"]


def test_decide_loads_report_from_reports_dir(env):
    assert (env.local / "reports" / "2026-11-23.json").exists()
    assert not (env.kb / "learn" / "reports").exists()
    row = decide.decide(env.cfg, RID, "defer", None)
    assert row["id"] == RID and row["decision"] == "defer"


def test_decide_ignores_old_report_worktree(env, monkeypatch, capsys):
    (env.local / "reports" / "2026-11-23.json").unlink()
    old = env.wt_root / "learn-report-2026-11-23" / "learn" / "reports"
    old.mkdir(parents=True)
    (old / "2026-11-23.json").write_text(report.to_json(_report()))
    with pytest.raises(decide.DecideError) as err:
        decide.decide(env.cfg, RID, "defer", None)
    assert err.value.code == 2 and "no report found" in str(err.value)
    assert env.cli(monkeypatch, RID, "defer") == 2
    assert "no report found" in capsys.readouterr().err


def test_accept_no_repo_exit_3(env, monkeypatch):
    monkeypatch.setenv("GH_PUSH", "false")
    cfg = learn_config.LearnConfig(kb=env.kb, reports_dir=env.local)
    with pytest.raises(decide.DecideError) as err:
        decide.decide(cfg, RID, "accept", None)
    assert err.value.code == 3 and "no repo to file in" in str(err.value)
    assert env.rows() == []
    assert env.gh_calls("issue", "create") == []


def test_accept_twice_files_once(env):
    first = decide.decide(env.cfg, RID, "accept", None)
    second = decide.decide(env.cfg, RID, "accept", None)
    assert second == first
    assert len(env.gh_calls("issue", "create")) == 1
    assert len(env.rows()) == 1


def test_typed_after_a_click_reports_the_existing_decision(env, monkeypatch, capsys):
    assert env.cli(monkeypatch, RID, "accept") == 0
    capsys.readouterr()
    assert env.cli(monkeypatch, RID, "reject", "--reason-stdin", stdin="changed my mind") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "accept"
    assert len(env.rows()) == 1


def test_reject_requires_reason(env, monkeypatch, capsys):
    assert env.cli(monkeypatch, RID, "reject", "--reason-stdin", stdin="  \n ") == 2
    assert env.cli(monkeypatch, RID, "reject") == 2
    assert env.rows() == []
    assert "reason" in capsys.readouterr().err


def test_reject_suppresses_fingerprint(env):
    decide.decide(env.cfg, RID, "reject", "not worth it")
    assert "alpha|cost_growth" in candidates.suppressed(env.decisions)
    assert env.gh_calls("issue", "create") == []


def test_defer_logs_without_filing(env):
    row = decide.decide(env.cfg, RID, "defer", None)
    assert row["decision"] == "defer" and row["issue_url"] is None and row["repo"] is None
    assert env.gh_calls("issue", "create") == []


def test_issue_title_neutralizes_newlines(env):
    env.write_report(_report(skill="al\npha\r\n## x"))
    decide.decide(env.cfg, RID, "accept", None)
    (create,) = env.gh_calls("issue", "create")
    title = create[create.index("--title") + 1]
    assert "\n" not in title and "\r" not in title
    assert title.endswith(f"(cost_growth) ({RID})") or title.endswith(f"cost_growth ({RID})")


def test_event_has_no_reason_text(env):
    decide.decide(env.cfg, RID, "reject", "my private words")
    (event,) = env.events
    text = json.dumps(event)
    assert "my private words" not in text
    assert "cta.learn.decision" in text
    attrs = {a["key"]: a["value"]["stringValue"]
             for a in event["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]}
    assert attrs["id"] == RID and attrs["skill"] == "alpha"
    assert attrs["signal"] == "cost_growth" and attrs["decision"] == "reject"
    assert "reason" not in attrs


def test_send_failure_is_a_warning(env, monkeypatch, capsys):
    def boom(event, endpoint):
        raise OSError("down")

    monkeypatch.setattr(decide, "send", boom)
    assert env.cli(monkeypatch, RID, "defer") == 0
    assert "warning" in capsys.readouterr().err
    assert len(env.rows()) == 1


def test_missing_gitleaks_fails_closed_with_exit_4(env, monkeypatch):
    env.use_no_gitleaks(monkeypatch)
    assert env.cli(monkeypatch, RID, "accept") == 4
    assert env.gh_calls("issue", "create") == []
    assert env.rows() == []


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_secret_in_body_refuses(env, monkeypatch, capsys):
    env.use_real_gitleaks(monkeypatch)
    token = "ghp_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
    env.write_report(_report(problem=f"the token {token} leaks"))
    assert env.cli(monkeypatch, RID, "accept") == 4
    assert env.gh_calls("issue", "create") == []
    assert env.rows() == []
    assert token not in capsys.readouterr().err


def test_reason_with_dollar_paren_logged_verbatim(env, monkeypatch):
    reason = "no $(touch /tmp/x) and `id` and \"quotes\" ; rm -rf"
    assert env.cli(monkeypatch, RID, "reject", "--reason-stdin", stdin=reason + "\n") == 0
    assert env.rows()[0]["reason"] == reason


@pytest.mark.parametrize("bad", ["x", "2026-11-23-R6", "2026-11-23-R0", "2026-13-40-R1",
                                 "2026-11-23-R1; rm -rf", "../../etc/passwd",
                                 "2026-11-23-R1\n", ""])
def test_bad_id_exit_2(env, monkeypatch, bad):
    assert env.cli(monkeypatch, bad, "accept") == 2
    assert env.gh_calls() == []
    assert env.rows() == []


def test_unknown_id_exit_2(env, monkeypatch):
    assert env.cli(monkeypatch, "2026-11-23-R2", "accept") == 2
    assert env.rows() == []


def test_row_feeds_followups_and_suppression(env):
    decide.decide(env.cfg, RID, "accept", None)
    row = env.rows()[0]
    assert row["signal"] == "cost_growth" and row["metric"] == "cost_ratio"
    assert row["value"] == 2.0
    # the real layout: the report reads the live checkout, the row sits only on the worktree
    assert not (env.kb / "learn" / "decisions.jsonl").exists()
    cfg = learn_config.LearnConfig(kb=env.kb, reports_dir=env.kb.parent / "local")
    week = Week(start=date(2026, 11, 23), end=date(2026, 11, 30))
    got = report._followups(cfg, week, env.kb / "learn" / "reports", date(2026, 11, 30),
                              report._decision_files(cfg))
    assert [f.id for f in got] == [RID]


def test_rejection_suppresses_from_the_worktree(env):
    decide.decide(env.cfg, RID, "reject", "not now")
    assert not (env.kb / "learn" / "decisions.jsonl").exists()
    files = report._decision_files(learn_config.LearnConfig(kb=env.kb))
    assert candidates.suppressed(files) == {"alpha|cost_growth"}


def _remote(env, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True,
                   capture_output=True)
    git(env.kb, "remote", "add", "origin", str(remote))
    git(env.kb, "push", "-u", "origin", "main")
    git(env.kb, "remote", "set-head", "origin", "main")
    return remote


def _clone(tmp_path, remote, name):
    clone = tmp_path / f"clone-{name}"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True,
                   capture_output=True)
    git(clone, "config", "user.name", "Learn Test")
    git(clone, "config", "user.email", "learn-test@example.invalid")
    git(clone, "config", "commit.gpgsign", "false")
    return clone


def test_new_worktree_is_cut_from_the_fetched_default_branch(env, tmp_path):
    remote = _remote(env, tmp_path)
    clone = _clone(tmp_path, remote, "a")
    (clone / "elsewhere.txt").write_text("new on the remote\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-m", "remote work")
    git(clone, "push", "origin", "main")
    decide.decide(env.cfg, RID, "defer", None)
    assert (env.worktree / "elsewhere.txt").exists()


def test_reused_worktree_is_reset_after_the_decisions_pr_merged(env, tmp_path):
    remote = _remote(env, tmp_path)
    decide.decide(env.cfg, RID, "defer", None)  # pushes learn/decisions, opens the PR
    first = env.rows()[0]
    # the PR is squash-merged: the default branch gets the row in a different commit
    clone = _clone(tmp_path, remote, "b")
    (clone / "learn").mkdir(exist_ok=True)
    (clone / "learn" / "decisions.jsonl").write_text(json.dumps(first) + "\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-m", "squash of the decisions PR")
    git(clone, "push", "origin", "main")
    (env.state / "pr").unlink()  # no open PR any more
    rep = _report()
    rep.recommendations.append(Recommendation(
        "2026-11-23-R2", rep.recommendations[0].candidate, problem="p", why="w", change="c",
        measure="m"))
    env.write_report(rep)
    decide.decide(env.cfg, "2026-11-23-R2", "defer", None)
    ids = [r["id"] for r in env.rows()]
    assert ids == [RID, "2026-11-23-R2"]  # no duplicate of the merged row
    assert "squash of the decisions PR" in git(env.worktree, "log", "--format=%s")
    assert git(remote, "show", "learn/decisions:learn/decisions.jsonl").count("\n") == 2
    assert len(env.gh_calls("pr", "create")) == 2  # a fresh PR for the new branch state


def test_pushes_and_opens_the_pr_once(env, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True,
                   capture_output=True)
    git(env.kb, "remote", "add", "origin", str(remote))
    git(env.kb, "push", "origin", "main")
    decide.decide(env.cfg, RID, "defer", None)
    assert "learn/decisions" in git(remote, "branch", "--list")
    assert len(env.gh_calls("pr", "create")) == 1
    rep = _report()
    rep.recommendations.append(Recommendation(
        id="2026-11-23-R2", candidate=rep.recommendations[0].candidate, problem="p", why="w",
        change="c", measure="m"))
    env.write_report(rep)
    decide.decide(env.cfg, "2026-11-23-R2", "defer", None)
    assert len(env.gh_calls("pr", "create")) == 1
    assert len(env.rows()) == 2


def test_send_refuses_non_http_endpoint():
    with pytest.raises(ValueError):
        decide.send({}, "file:///etc/passwd")


def test_accept_sets_up_worktree_before_filing(env, monkeypatch):
    def boom(cfg):
        raise decide.DecideError(1, "worktree setup failed")
    monkeypatch.setattr(decide, "_worktree", boom)
    assert env.cli(monkeypatch, RID, "accept") != 0
    assert env.gh_calls("issue", "create") == []
    assert env.rows() == []


def test_gitleaks_ignores_inherited_config_env(monkeypatch):
    monkeypatch.setenv("GITLEAKS_CONFIG", "/nonexistent/allow-all.toml")
    monkeypatch.setenv("GITLEAKS_CONFIG_TOML", "[allowlist]")
    seen = []

    def fake_run(argv, cwd=None, env=None, **kw):
        seen.append((argv, env))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(decide.subprocess, "run", fake_run)
    with pytest.raises(decide.DecideError):  # the fake writes no report
        decide._scan("hello")
    argv, passed = next((a, e) for a, e in seen if a[0] == "gitleaks")
    assert "GITLEAKS_CONFIG" not in passed
    assert "GITLEAKS_CONFIG_TOML" not in passed
