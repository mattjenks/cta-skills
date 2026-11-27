import json
import subprocess
from datetime import date

import gather
import learn_config
import rot
from model import RotItem, Week
from rot import broken_skills, connectors, permissions, stale_rules


def _cfg(tmp_path, repos=(), kb=None, owners=("Corp",)):
    return learn_config.LearnConfig(kb=kb, repos=tuple(repos), exclude_owners=owners)


def _week(**events):
    week = Week(start=date(2026, 11, 16), end=date(2026, 11, 23))
    week.events.update(events)
    return week


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _plugins(monkeypatch, tmp_path, entries):
    """entries: {"plugin@market": install_dir}; markets map to owners via `_markets`."""
    data = {"version": 2, "plugins": {k: [{"installPath": str(v)}] for k, v in entries.items()}}
    monkeypatch.setattr(broken_skills, "INSTALLED_PLUGINS", _write(
        tmp_path / "home" / "installed_plugins.json", json.dumps(data)))


def _markets(monkeypatch, tmp_path, **owners):
    data = {m: {"source": {"repo": f"{o}/{m}"}} for m, o in owners.items()}
    monkeypatch.setattr(gather, "KNOWN_MARKETPLACES",
                        _write(tmp_path / "home" / "known.json", json.dumps(data)))


def _no_plugins(monkeypatch, tmp_path):
    monkeypatch.setattr(broken_skills, "INSTALLED_PLUGINS", tmp_path / "none.json")


def test_broken_link_and_frontmatter(tmp_path, monkeypatch):
    _no_plugins(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    skills = repo / ".claude" / "skills"
    _write(skills / "ok" / "SKILL.md", "---\nname: ok\ndescription: fine\n---\nsee [a](a.md)\n")
    _write(skills / "ok" / "a.md", "x")
    _write(skills / "nodesc" / "SKILL.md", "---\nname: nodesc\n---\nbody\n")
    _write(skills / "link" / "SKILL.md",
           "---\nname: link\ndescription: d\n---\nline\nsee [gone](missing.md#top) and "
           "[web](https://example.test/x)\n")
    items = broken_skills.check(_week(), _cfg(tmp_path, repos=[repo]))
    assert all(i.kind == "broken" for i in items)
    by_loc = {i.location: i for i in items}
    assert set(by_loc) == {f"{skills / 'nodesc' / 'SKILL.md'}:1",
                           f"{skills / 'link' / 'SKILL.md'}:6"}
    assert "description" in by_loc[f"{skills / 'nodesc' / 'SKILL.md'}:1"].problem
    assert "missing.md" in by_loc[f"{skills / 'link' / 'SKILL.md'}:6"].problem


def test_installed_personal_plugin_skill_is_scanned(tmp_path, monkeypatch):
    plugin = tmp_path / "cache" / "mine"
    _write(plugin / "skills" / "s" / "SKILL.md", "---\nname: s\n---\n")
    _plugins(monkeypatch, tmp_path, {"mine@mk": plugin})
    _markets(monkeypatch, tmp_path, mk="me")
    items = broken_skills.check(_week(), _cfg(tmp_path))
    assert len(items) == 1 and "description" in items[0].problem


def test_excluded_owner_plugin_not_scanned(tmp_path, monkeypatch):
    work, mine = tmp_path / "cache" / "work", tmp_path / "cache" / "mine"
    for plugin in (work, mine):
        _write(plugin / "skills" / "s" / "SKILL.md", "---\nname: s\n---\n")
    _plugins(monkeypatch, tmp_path, {"work@wk": work, "mine@mk": mine})
    _markets(monkeypatch, tmp_path, wk="Corp", mk="me")
    items = broken_skills.check(_week(), _cfg(tmp_path))
    assert [i.location for i in items] == [f"{mine / 'skills' / 's' / 'SKILL.md'}:1"]


def _git_repo(path, origin):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)


def test_work_repo_skipped(tmp_path, monkeypatch):
    _no_plugins(monkeypatch, tmp_path)
    work, mine = tmp_path / "work", tmp_path / "mine"
    _git_repo(work, "git@github.com:Corp/app.git")
    _git_repo(mine, "https://github.com/me/app")
    for repo in (work, mine):
        _write(repo / ".claude" / "skills" / "s" / "SKILL.md", "---\nname: s\n---\n")
        _write(repo / "CLAUDE.md", "see `docs/gone.md`\n")
        (repo / "docs").mkdir()
    cfg = _cfg(tmp_path, repos=[work, mine])
    for check in (broken_skills.check, stale_rules.check):
        items = check(_week(), cfg)
        assert items and all(str(work) not in i.location for i in items)
        assert any(str(mine) in i.location for i in items)


def test_stale_rule_found_and_url_skipped(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md",
           "Use `scripts/gone.py` and `scripts/here.py`.\nDocs at `https://example.test/a/b.md`.\n"
           "Keep `README.md` and `notes/gone.txt` too.\n")
    _write(repo / "scripts" / "here.py", "x")
    _write(repo / "README.md", "x")
    (repo / "notes").mkdir()
    items = stale_rules.check(_week(), _cfg(tmp_path, repos=[repo]))
    assert [(i.kind, i.location) for i in items] == [
        ("stale", f"{repo / 'CLAUDE.md'}:1"), ("stale", f"{repo / 'CLAUDE.md'}:3")]
    assert "scripts/gone.py" in items[0].problem and "notes/gone.txt" in items[1].problem


def test_stale_rule_ignores_placeholders_and_code_fences(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md",
           "`<dir>/file.md` `src/*.py` `~/x/y.md` `/abs/path.md` `../up/x.md`\n"
           "```\n`in/fence.md`\nin/fence2.md\n```\n"
           "~~~\n`tilde/fence.md`\n~~~\n"
           "`after/fence.md`\n")
    (repo / "after").mkdir()
    items = stale_rules.check(_week(), _cfg(tmp_path, repos=[repo]))
    assert [i.location for i in items] == [f"{repo / 'CLAUDE.md'}:9"]


def test_stale_rules_cover_kb_files(tmp_path):
    kb = tmp_path / "kb"
    _write(kb / "CLAUDE.md", "`a/gone.md`\n")
    _write(kb / "PREFERENCES.md", "`b/gone.md`\n")
    _write(kb / "OTHER.md", "`c/gone.md`\n")
    (kb / "a").mkdir()
    (kb / "b").mkdir()
    items = stale_rules.check(_week(), _cfg(tmp_path, kb=kb))
    assert sorted(i.location for i in items) == [f"{kb / 'CLAUDE.md'}:1",
                                                 f"{kb / 'PREFERENCES.md'}:1"]


def test_stale_skips_email(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md", "Write to `someone@example.com` for access.\n")
    assert stale_rules.check(_week(), _cfg(tmp_path, repos=[repo])) == []


def test_stale_skips_bare_file_name(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md", "Read `design.md` and `SKILL.md` first.\n")
    assert stale_rules.check(_week(), _cfg(tmp_path, repos=[repo])) == []


def test_stale_skips_missing_parent(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md", "Settings live in `Metadata/model_settings.config`.\n")
    assert stale_rules.check(_week(), _cfg(tmp_path, repos=[repo])) == []


def test_stale_flags_missing_file_in_real_folder(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md", "See `docs/gone.md`.\n")
    (repo / "docs").mkdir()
    items = stale_rules.check(_week(), _cfg(tmp_path, repos=[repo]))
    assert len(items) == 1 and "docs/gone.md" in items[0].problem


def test_connector_failures_counted():
    events = [{"server_name": "alpha", "status": "failed"}, {"server_name": "alpha", "status": "failed"},
              {"server_name": "alpha", "status": "connected"},
              {"server_name": "beta", "status": "connected"},
              {"server_name": "gamma", "status": "needs-auth"}]
    items = connectors.check(_week(mcp_server_connection=events), learn_config.LearnConfig(kb=None))
    by_loc = {i.location: i for i in items}
    assert set(by_loc) == {"alpha", "gamma"}
    assert by_loc["alpha"].kind == "broken" and "2" in by_loc["alpha"].problem
    assert "1" in by_loc["gamma"].problem


def _decisions(n, decision, source, tool="Bash", word="gh"):
    row = {"tool_name": tool, "decision": decision, "source": source}
    if word:
        row["command_word"] = word
    return [dict(row) for _ in range(n)]


def test_permission_prompt_suggests_allow_rule():
    events = (_decisions(5, "accept", "user_temporary") + _decisions(4, "accept", "user_permanent", word="git")
              + _decisions(3, "reject", "config", word="rm")
              + _decisions(2, "reject", "config", word="ls")
              + _decisions(4, "accept", "user_temporary", word="jq")
              + _decisions(5, "accept", "config", word="cat")
              + _decisions(6, "accept", "user_temporary", tool="WebFetch", word=None))
    items = permissions.check(_week(tool_decision=events), learn_config.LearnConfig(kb=None))
    assert all(i.kind == "permission" for i in items)
    by_loc = {i.location: i for i in items}
    assert set(by_loc) == {"Bash(gh:*)", "Bash(rm:*)", "WebFetch"}
    assert "allow" in by_loc["Bash(gh:*)"].fix and "Bash(gh:*)" in by_loc["Bash(gh:*)"].fix
    assert "blocked by a rule" in by_loc["Bash(rm:*)"].problem
    assert "WebFetch" in by_loc["WebFetch"].fix


def test_permission_rule_text_only_safe_words():
    events = (_decisions(5, "accept", "user_temporary", word="$(x)")
              + _decisions(5, "accept", "user_temporary", tool="Bad Tool)", word="ok")
              + _decisions(5, "accept", "user_temporary", word=None)  # a bare Bash rule allows everything
              + _decisions(3, "reject", "config", word="rm -rf"))
    assert permissions.check(_week(tool_decision=events), learn_config.LearnConfig(kb=None)) == []


def test_run_rot_has_no_cap(tmp_path, monkeypatch):
    _no_plugins(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md", "".join(f"`gone/f{i}.md`\n" for i in range(7)))
    (repo / "gone").mkdir()
    items, totals, errors = rot.run_rot(_week(), _cfg(tmp_path, repos=[repo]))
    assert len(items["stale"]) == 7 and totals["stale"] == 7
    assert totals["broken"] == 0 and totals["permission"] == 0 and items["broken"] == []
    assert errors == []
    assert isinstance(items["stale"][0], RotItem)


def test_run_rot_drops_rejected(tmp_path, monkeypatch):
    _no_plugins(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    _write(repo / "CLAUDE.md", "`gone/a.md` and `gone/b.md`\n")
    (repo / "gone").mkdir()
    cfg = _cfg(tmp_path, repos=[repo])
    first = rot.run_rot(_week(), cfg)[0]["stale"]
    assert len(first) == 2
    items, totals, _ = rot.run_rot(_week(), cfg, {first[0].fingerprint})
    assert [i.fingerprint for i in items["stale"]] == [first[1].fingerprint]
    assert totals["stale"] == 1


def test_stale_fingerprint_ignores_line_number(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    _write(repo / "CLAUDE.md", "\n\n`docs/gone.md`\n")
    at3 = stale_rules.check(_week(), _cfg(tmp_path, repos=[repo]))
    _write(repo / "CLAUDE.md", "\n" * 8 + "`docs/gone.md`\n")
    at9 = stale_rules.check(_week(), _cfg(tmp_path, repos=[repo]))
    assert at3[0].location.endswith(":3") and at9[0].location.endswith(":9")
    assert at3[0].fingerprint == at9[0].fingerprint == f"stale|{repo / 'CLAUDE.md'}|docs/gone.md"


def test_stale_item_carries_origin_repo(tmp_path):
    repo = tmp_path / "repo"
    _git_repo(repo, "git@github.com:owner/repo.git")
    (repo / "docs").mkdir()
    _write(repo / "CLAUDE.md", "`docs/gone.md`\n")
    items = stale_rules.check(_week(), _cfg(tmp_path, repos=[repo]))
    assert items[0].repo == "owner/repo" and items[0].accept is True


def test_stale_repo_empty_without_origin(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    _write(repo / "CLAUDE.md", "`docs/gone.md`\n")
    assert stale_rules.check(_week(), _cfg(tmp_path, repos=[repo]))[0].repo == ""


def test_broken_skill_fingerprints_and_repo(tmp_path, monkeypatch):
    plugin = tmp_path / "cache" / "mine"
    _write(plugin / "skills" / "s" / "SKILL.md", "---\nname: s\n---\n[x](gone.md)\n")
    _plugins(monkeypatch, tmp_path, {"mine@mk": plugin})
    _markets(monkeypatch, tmp_path, mk="me")
    skill = plugin / "skills" / "s" / "SKILL.md"
    items = broken_skills.check(_week(), _cfg(tmp_path))
    assert sorted(i.fingerprint for i in items) == sorted([
        "broken|mine@mk/skills/s/SKILL.md|frontmatter|description",
        "broken|mine@mk/skills/s/SKILL.md|link|gone.md"])
    assert {i.repo for i in items} == {"me/mk"} and all(i.accept for i in items)


def test_broken_skill_in_repo_has_no_repo(tmp_path, monkeypatch):
    _no_plugins(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    skill = _write(repo / ".claude" / "skills" / "s" / "SKILL.md", "---\n---\n")
    items = broken_skills.check(_week(), _cfg(tmp_path, repos=[repo]))
    assert [i.fingerprint for i in items] == [
        "broken|.claude/skills/s/SKILL.md|frontmatter|description,name"]
    assert str(tmp_path) not in items[0].fingerprint
    assert items[0].repo == ""


def test_broken_repo_skill_fingerprint_names_its_repo(tmp_path, monkeypatch):
    _no_plugins(monkeypatch, tmp_path)
    for name in ("one", "two"):
        repo = tmp_path / name
        _git_repo(repo, f"git@github.com:owner/{name}.git")
        _write(repo / ".claude" / "skills" / "s" / "SKILL.md", "---\nname: s\n---\n[x](gone.md)\n")
    items = broken_skills.check(_week(), _cfg(tmp_path, repos=[tmp_path / "one", tmp_path / "two"]))
    prints = sorted(i.fingerprint for i in items)
    assert prints == ["broken|owner/one/.claude/skills/s/SKILL.md|frontmatter|description",
                      "broken|owner/one/.claude/skills/s/SKILL.md|link|gone.md",
                      "broken|owner/two/.claude/skills/s/SKILL.md|frontmatter|description",
                      "broken|owner/two/.claude/skills/s/SKILL.md|link|gone.md"]
    assert all(str(tmp_path) not in p for p in prints)
    assert all(i.repo == "" for i in items)


def test_broken_plugin_fingerprint_survives_a_version_change(tmp_path, monkeypatch):
    _markets(monkeypatch, tmp_path, mk="me")
    prints = []
    for version in ("1.0.0", "1.1.0"):
        plugin = tmp_path / "cache" / "mk" / "mine" / version
        _write(plugin / "skills" / "s" / "SKILL.md", "---\nname: s\n---\n[x](gone.md)\n")
        _plugins(monkeypatch, tmp_path, {"mine@mk": plugin})
        prints.append(sorted(i.fingerprint for i in broken_skills.check(_week(), _cfg(tmp_path))))
    assert prints[0] == prints[1] and len(prints[0]) == 2
    assert all("1.0.0" not in p and "1.1.0" not in p for p in prints[0])


def test_connector_items_not_acceptable():
    events = [{"server_name": "alpha", "status": "failed"}]
    items = connectors.check(_week(mcp_server_connection=events), learn_config.LearnConfig(kb=None))
    assert items[0].accept is False
    assert items[0].fingerprint == "broken|connector|alpha|failed"


def test_connector_fingerprint_status_cleaned():
    events = [{"server_name": "alpha", "status": "fa\nil|ed"}]
    items = connectors.check(_week(mcp_server_connection=events), learn_config.LearnConfig(kb=None))
    fp = items[0].fingerprint
    assert "\n" not in fp and fp.count("|") == 3 and fp.startswith("broken|connector|alpha|")


def test_permission_fingerprints():
    events = (_decisions(5, "accept", "user_temporary") + _decisions(3, "reject", "config", word="rm"))
    items = permissions.check(_week(tool_decision=events), learn_config.LearnConfig(kb=None))
    assert {i.fingerprint for i in items} == {"permission|Bash(gh:*)|prompted",
                                              "permission|Bash(rm:*)|blocked"}
    assert all(i.accept for i in items)


def test_origin_repo_github_only(tmp_path):
    from rot import _common
    for url, want in (("git@github.com:o/n.git", "o/n"), ("https://github.com/o/n", "o/n"),
                      ("https://github.com/o/n.git", "o/n"),
                      ("https://evil.example/o/n.git", None),
                      ("https://github.com.evil.example/o/n.git", None)):
        repo = tmp_path / "r"
        if repo.exists():
            subprocess.run(["git", "-C", str(repo), "remote", "remove", "origin"], check=True)
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)
        else:
            _git_repo(repo, url)
        assert _common.origin_repo(repo) == want, url
    assert _common.origin_repo(tmp_path / "nope") is None


def test_suppressed_ignores_empty_fingerprint(tmp_path):
    import candidates
    log = _write(tmp_path / "d.jsonl", json.dumps({"decision": "reject", "fingerprint": ""}) + "\n")
    assert candidates.suppressed(log) == set()


def test_run_rot_names_a_failing_check(tmp_path, monkeypatch):
    _no_plugins(monkeypatch, tmp_path)

    def boom(week, cfg):
        raise RuntimeError("x")

    monkeypatch.setattr(connectors, "check", boom)
    items, totals, errors = rot.run_rot(_week(), _cfg(tmp_path))
    assert errors == ["rot connectors: failed (RuntimeError)"]


def test_items_are_sanitized(tmp_path):
    kb = tmp_path / "kb"
    _write(kb / "CLAUDE.md", "`a[b](c)/gone.md`\n")
    (kb / "a[b](c)").mkdir()
    items = stale_rules.check(_week(), _cfg(tmp_path, kb=kb))
    assert items and not any(c in items[0].problem for c in "[]()")
