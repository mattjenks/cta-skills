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
from model import Candidate, Recommendation, Report, RotItem, SkillUsage, Week

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
    print(os.environ.get("GH_PRIVATE", "true") if ".private" in args
          else os.environ.get("GH_PUSH", "true"))
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


def _record_subprocess(monkeypatch):
    calls = []
    real = subprocess.run

    def spy(argv, *a, **kw):
        calls.append([str(x) for x in argv])
        return real(argv, *a, **kw)
    monkeypatch.setattr(decide.subprocess, "run", spy)
    return calls


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.kb = tmp_path / "kb"
        self.local = tmp_path / "local"
        self.state = tmp_path / "gh-state"
        self.state.mkdir()
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
        monkeypatch.setattr(decide, "send", lambda event, endpoint: self.events.append(event))
        self.write_report(_report())

    def write_report(self, rep):
        self.kb.mkdir(exist_ok=True)
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
    def decisions(self):
        return learn_config.decisions_path(self.cfg)

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
    assert f"--repo={SKILL_REPO}" in create
    assert create[create.index("--title") + 1] == f"alpha: cost_growth ({RID})"
    assert create[create.index("--label") + 1] == "cta-learn"
    assert "--body-file" in create
    assert env.gh_calls("label", "create")
    assert env.rows() == [row]


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
    old = env.tmp / "worktrees" / "learn-report-2026-11-23" / "learn" / "reports"
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
    assert not (env.kb / "learn" / "decisions.jsonl").exists()
    week = Week(start=date(2026, 11, 23), end=date(2026, 11, 30))
    got = report._followups(env.cfg, week, env.local / "reports", date(2026, 11, 30),
                            report._decision_files(env.cfg))
    assert [f.id for f in got] == [RID]


def test_rejection_suppresses_from_the_local_log(env):
    decide.decide(env.cfg, RID, "reject", "not now")
    assert not (env.kb / "learn" / "decisions.jsonl").exists()
    files = report._decision_files(env.cfg)
    assert files == [env.local / "decisions.jsonl"]
    assert candidates.suppressed(files) == {"alpha|cost_growth"}


def test_decision_appends_to_local_log(env, monkeypatch):
    calls = _record_subprocess(monkeypatch)
    row = decide.decide(env.cfg, RID, "defer", None)
    assert env.rows() == [row]
    assert env.decisions == env.local / "decisions.jsonl"
    assert [c for c in calls if c[0] == "git"] == []


def test_accept_runs_no_git_or_pr(env, monkeypatch):
    calls = _record_subprocess(monkeypatch)
    decide.decide(env.cfg, RID, "accept", None)
    assert [c for c in calls if c[0] == "git"] == []
    assert env.gh_calls("pr") == []
    gh = [c[1:3] for c in calls if c[0] == "gh"]
    assert ["label", "create"] in gh and ["issue", "create"] in gh
    assert all(g[0] in ("api", "label", "issue") for g in gh)


def test_repeat_id_returns_existing_row_from_local_log(env):
    first = decide.decide(env.cfg, RID, "defer", None)
    assert decide.decide(env.cfg, RID, "reject", "changed my mind") == first
    assert len(env.rows()) == 1


def test_send_refuses_non_http_endpoint():
    with pytest.raises(ValueError):
        decide.send({}, "file:///etc/passwd")


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


# ---------------------------------------------------------------- rot items

S1 = "2026-11-23-S1"


def _stale(repo="owner/repo", fp="stale|CLAUDE.md|docs/gone.md"):
    return RotItem("stale", "CLAUDE.md:12", "names docs/gone.md, which does not exist",
                   "update or remove the line", fingerprint=fp, repo=repo)


def _perm(blocked=False):
    rule = "Bash(git:*)"
    if blocked:
        return RotItem("permission", rule, "blocked by a rule 4 times",
                       f"review the deny rule for {rule} if it should be allowed",
                       fingerprint=f"permission|{rule}|blocked")
    return RotItem("permission", rule, "prompted 5 times", f"add an allow rule: {rule}",
                   fingerprint=f"permission|{rule}|prompted")


def _broken(problem="link to missing.md does not exist"):
    return RotItem("broken", "skills/x/SKILL.md:7", problem, "fix the link or restore the file",
                   fingerprint="broken|skills/x/SKILL.md|link|missing.md", repo="owner/repo")


def _connector():
    return RotItem("broken", "srv", "3 connection attempts ended failed", "sign in again",
                   fingerprint="broken|connector|srv|failed", accept=False)


def _put_rot(env, broken=(), stale=(), permission=()):
    rep = _report()
    rep.rot = {"broken": list(broken), "stale": list(stale), "permission": list(permission)}
    report.assign_rot_ids(rep.rot, rep.date)
    env.write_report(rep)


def _capture_issue(monkeypatch):
    seen = {}
    real = decide._gh

    def spy(argv, **kw):
        if argv[:2] == ["issue", "create"]:
            seen["title"] = argv[argv.index("--title") + 1]
            seen["body"] = Path(argv[argv.index("--body-file") + 1]).read_text()
        return real(argv, **kw)
    monkeypatch.setattr(decide, "_gh", spy)
    return seen


def test_reject_rot_logs_fingerprint(env):
    _put_rot(env, stale=[_stale()])
    row = decide.decide(env.cfg, S1, "reject", "intended")
    assert row["fingerprint"] == "stale|CLAUDE.md|docs/gone.md"
    assert row["signal"] == "rot:stale" and row["kind"] == "stale"
    assert row["skill"] == "" and row["metric"] == "" and row["value"] is None
    assert row["decision"] == "reject" and row["reason"] == "intended"
    assert env.rows() == [row]
    assert env.gh_calls("issue", "create") == []


def test_accept_stale_files_issue_in_item_repo(env, monkeypatch):
    _put_rot(env, stale=[_stale()])
    seen = _capture_issue(monkeypatch)
    row = decide.decide(env.cfg, S1, "accept", None)
    assert row["repo"] == "owner/repo" and row["signal"] == "rot:stale"
    (create,) = env.gh_calls("issue", "create")
    assert "--repo=owner/repo" in create
    assert seen["title"] == "Stale rule: `CLAUDE.md` names `docs/gone.md`"
    lines = seen["body"].splitlines()
    assert "File: `CLAUDE.md`, line `12`" in lines
    assert "Missing: `docs/gone.md`" in lines
    assert "Fix: update or remove the line" in lines
    assert lines[-2:] == ["Report: 2026-11-23", f"ID: {S1}"]
    assert env.rows() == [row]


def test_accept_stale_unwritable_repo_uses_fallback(env, monkeypatch):
    _put_rot(env, stale=[_stale()])
    monkeypatch.setenv("GH_PUSH", "false")
    row = decide.decide(env.cfg, S1, "accept", None)
    assert row["repo"] == FALLBACK
    (create,) = env.gh_calls("issue", "create")
    assert f"--repo={FALLBACK}" in create


def test_accept_stale_no_repo_no_fallback_exits_3(env):
    _put_rot(env, stale=[_stale(repo="")])
    cfg = learn_config.LearnConfig(kb=env.kb, reports_dir=env.local)
    with pytest.raises(decide.DecideError) as err:
        decide.decide(cfg, S1, "accept", None)
    assert err.value.code == 3 and "no repo to file in" in str(err.value)
    assert env.gh_calls("issue", "create") == [] and env.rows() == []


def test_accept_stale_public_fallback_exits_3(env, monkeypatch):
    _put_rot(env, stale=[_stale(repo="")])
    monkeypatch.setenv("GH_PRIVATE", "false")
    with pytest.raises(decide.DecideError) as err:
        decide.decide(env.cfg, S1, "accept", None)
    assert err.value.code == 3
    assert env.gh_calls("issue", "create") == [] and env.rows() == []


def test_accept_stale_private_fallback_files(env):
    _put_rot(env, stale=[_stale(repo="")])
    assert decide.decide(env.cfg, S1, "accept", None)["repo"] == FALLBACK


def test_accept_permission_uses_fallback(env, monkeypatch):
    _put_rot(env, permission=[_perm(), _perm(blocked=True)])
    seen = _capture_issue(monkeypatch)
    monkeypatch.setenv("GH_PRIVATE", "false")  # only stale items need a private fallback
    row = decide.decide(env.cfg, "2026-11-23-P1", "accept", None)
    assert row["repo"] == FALLBACK
    assert seen["title"] == "Permission: add `Bash(git:*)`"
    lines = seen["body"].splitlines()
    assert "Rule: `Bash(git:*)`" in lines
    assert "This week: `prompted 5 times`" in lines
    assert "Settings: ~/.claude/settings.json, permissions.allow" in lines
    assert "Applying it needs the owner's approval." in lines
    decide.decide(env.cfg, "2026-11-23-P2", "accept", None)
    assert seen["title"] == "Permission: review deny rule `Bash(git:*)`"


def test_accept_broken_skill_issue(env, monkeypatch):
    _put_rot(env, broken=[_broken()])
    seen = _capture_issue(monkeypatch)
    decide.decide(env.cfg, "2026-11-23-B1", "accept", None)
    assert seen["title"] == "Broken skill: `link to missing.md does not exist`"
    lines = seen["body"].splitlines()
    assert "File: `SKILL.md`" in lines
    assert "Problem: `link to missing.md does not exist`" in lines
    assert "Fix: `fix the link or restore the file`" in lines


def test_accept_broken_skill_public_fallback_exits_3(env, monkeypatch):
    item = _broken()
    item.repo = ""
    _put_rot(env, broken=[item])
    monkeypatch.setenv("GH_PRIVATE", "false")
    with pytest.raises(decide.DecideError) as err:
        decide.decide(env.cfg, "2026-11-23-B1", "accept", None)
    assert err.value.code == 3 and "not private" in str(err.value)
    assert env.gh_calls("issue", "create") == [] and env.rows() == []


def test_accept_permission_public_fallback_still_files(env, monkeypatch):
    _put_rot(env, permission=[_perm()])
    monkeypatch.setenv("GH_PRIVATE", "false")
    assert decide.decide(env.cfg, "2026-11-23-P1", "accept", None)["repo"] == FALLBACK


def test_accept_connector_exits_2(env):
    _put_rot(env, broken=[_connector()])
    with pytest.raises(decide.DecideError) as err:
        decide.decide(env.cfg, "2026-11-23-B1", "accept", None)
    assert err.value.code == 2
    assert env.gh_calls("issue", "create") == [] and env.rows() == []


def test_reject_connector_is_allowed(env):
    _put_rot(env, broken=[_connector()])
    row = decide.decide(env.cfg, "2026-11-23-B1", "reject", "known")
    assert row["fingerprint"] == "broken|connector|srv|failed"


def test_defer_rot_exits_2(env):
    _put_rot(env, stale=[_stale()])
    with pytest.raises(decide.DecideError) as err:
        decide.decide(env.cfg, S1, "defer", None)
    assert err.value.code == 2 and env.rows() == []


def test_rot_item_without_id_exits_2(env, monkeypatch):
    # the 2026-11-26 report shape: rot items carry no id and no fingerprint
    rep = _report()
    rep.rot = {"broken": [], "permission": [],
               "stale": [RotItem("stale", "CLAUDE.md:12", "p", "f")]}
    env.write_report(rep)
    assert env.cli(monkeypatch, S1, "reject", "--reason-stdin", stdin="x") == 2
    assert env.cli(monkeypatch, S1, "accept") == 2
    assert env.rows() == [] and env.gh_calls("issue", "create") == []


def test_unknown_rot_id_exits_2(env, monkeypatch):
    _put_rot(env, stale=[_stale()])
    assert env.cli(monkeypatch, "2026-11-23-S2", "accept") == 2


@pytest.mark.parametrize("fp", ["", "x" * 301, "stale|a\nb", "stale|a\x00b"])
def test_rot_empty_fingerprint_exits_2(env, fp):
    _put_rot(env, stale=[_stale(fp=fp)])
    for decision, reason in (("accept", None), ("reject", "why")):
        with pytest.raises(decide.DecideError) as err:
            decide.decide(env.cfg, S1, decision, reason)
        assert err.value.code == 2
    assert env.gh_calls("issue", "create") == [] and env.rows() == []


def test_rot_issue_values_in_code_spans(env, monkeypatch):
    _put_rot(env, broken=[_broken("link to @org/team")])
    seen = _capture_issue(monkeypatch)
    decide.decide(env.cfg, "2026-11-23-B1", "accept", None)
    for text in (seen["title"], seen["body"]):
        assert "`link to @org/team`" in text
        assert "@org/team" not in text.replace("`link to @org/team`", "")


def test_rot_issue_paths_are_masked(env, monkeypatch):
    _put_rot(env, broken=[_broken("see /home/tester/secret/notes.md")])
    seen = _capture_issue(monkeypatch)
    decide.decide(env.cfg, "2026-11-23-B1", "accept", None)
    assert "/home/tester" not in seen["body"] and "/home/tester" not in seen["title"]


def test_rot_title_and_body_scanned_together(env, monkeypatch):
    _put_rot(env, stale=[_stale()])
    scanned = []
    monkeypatch.setattr(decide, "_scan", lambda text: scanned.append(text))
    decide.decide(env.cfg, S1, "accept", None)
    (text,) = scanned
    assert text.startswith("Stale rule: ") and "Missing: `docs/gone.md`" in text


def test_rot_title_is_scanned(env, monkeypatch):
    _put_rot(env, stale=[_stale()])

    def refuse(text):
        if text.splitlines()[0].startswith("Stale rule"):
            raise decide.DecideError(4, "secret")
    monkeypatch.setattr(decide, "_scan", refuse)
    with pytest.raises(decide.DecideError) as err:
        decide.decide(env.cfg, S1, "accept", None)
    assert err.value.code == 4
    assert env.gh_calls("issue", "create") == [] and env.rows() == []


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_rot_issue_body_scanned(env, monkeypatch, capsys):
    env.use_real_gitleaks(monkeypatch)
    token = "ghp_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
    _put_rot(env, broken=[_broken(f"the token {token}")])
    assert env.cli(monkeypatch, "2026-11-23-B1", "accept") == 4
    assert env.gh_calls("issue", "create") == [] and env.rows() == []
    assert token not in capsys.readouterr().err


def test_rot_missing_gitleaks_fails_closed(env, monkeypatch):
    _put_rot(env, stale=[_stale()])
    env.use_no_gitleaks(monkeypatch)
    assert env.cli(monkeypatch, S1, "accept") == 4
    assert env.rows() == []


def test_rot_accept_row_skipped_by_followups(env):
    _put_rot(env, stale=[_stale()])
    decide.decide(env.cfg, S1, "accept", None)
    week = Week(start=date(2026, 11, 23), end=date(2026, 11, 30))
    got = report._followups(env.cfg, week, env.local / "reports", date(2026, 11, 30),
                            report._decision_files(env.cfg))
    assert got == []


def test_rot_repeat_returns_existing_row(env):
    _put_rot(env, stale=[_stale()])
    first = decide.decide(env.cfg, S1, "accept", None)
    assert decide.decide(env.cfg, S1, "accept", None) == first
    assert len(env.gh_calls("issue", "create")) == 1


@pytest.mark.parametrize("good", ["2026-11-23-B1", "2026-11-23-S12", "2026-11-23-P9999"])
def test_rot_id_pattern_accepts(good):
    assert decide.ID_PATTERN.fullmatch(good)


@pytest.mark.parametrize("bad", ["2026-11-23-B0", "2026-11-23-S01", "2026-11-23-P10000",
                                 "2026-11-23-X1", "2026-11-23-R10"])
def test_rot_id_pattern_rejects(bad):
    assert not decide.ID_PATTERN.fullmatch(bad)


def test_repo_pattern_rejects_leading_dash():
    assert not decide.REPO_PATTERN.fullmatch("-x/repo")
    assert not decide.REPO_PATTERN.fullmatch("owner/-repo")
    assert decide.REPO_PATTERN.fullmatch("owner/repo.name-1")
