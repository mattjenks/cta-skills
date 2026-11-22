import json
import subprocess
import sys
from pathlib import Path

import pytest

import finding_guard
from finding_guard import check

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "finding_guard.py"
PATH = ".cta/builds/x/security.json"
MESSAGE = 'only Matt closes findings; set "proposed-false-positive" with your reasoning'


def doc(status):
    return json.dumps({"findings": [{"id": "ab", "status": status, "reason": "why"}]})


# ---- Write / Edit / MultiEdit (resulting-state check) -----------------------------

def findings_doc(*pairs):
    return json.dumps({"findings": [{"id": i, "status": st, "reason": "why"} for i, st in pairs]}, indent=2)


@pytest.fixture
def sec(tmp_path):
    path = tmp_path / ".cta" / "builds" / "x" / "security.json"
    path.parent.mkdir(parents=True)
    path.write_text(findings_doc(("a1", "open"), ("b2", "proposed-false-positive"), ("c3", "false-positive")))
    return path


def edit(path, old, new, replace_all=False):
    return check("Edit", {"file_path": str(path), "old_string": old, "new_string": new,
                          "replace_all": replace_all})


@pytest.mark.parametrize("status", ["false-positive", "accepted-risk", " False-Positive ", "ACCEPTED-RISK"])
def test_closure_guard_blocks_write(status, tmp_path):
    path = tmp_path / PATH
    assert check("Write", {"file_path": str(path), "content": doc(status)}) == MESSAGE


@pytest.mark.parametrize("status", ["open", "fixed", "proposed-false-positive"])
def test_closure_guard_allows_proposed(status, tmp_path):
    assert check("Write", {"file_path": str(tmp_path / PATH), "content": doc(status)}) is None


def test_write_to_other_file_is_not_inspected(tmp_path):
    assert check("Write", {"file_path": "notes.md", "content": doc("accepted-risk")}) is None
    assert check("Write", {"file_path": "security.json.bak", "content": doc("accepted-risk")}) is None


def test_path_suffix_match_and_windows_separators():
    assert check("Write", {"file_path": "C:\\p\\Security.JSON", "content": doc("accepted-risk")})
    assert check("Write", {"file_path": "/x/my-security.json", "content": doc("accepted-risk")})


def test_escaped_status_in_json_is_decoded(tmp_path):
    content = '{"findings": [{"id": "z", "status": "false\\u002dpositive"}]}'
    assert check("Write", {"file_path": str(tmp_path / PATH), "content": content})


def test_write_preserving_closed_entries_is_allowed(sec):
    content = findings_doc(("a1", "fixed"), ("b2", "proposed-false-positive"), ("c3", "false-positive"))
    assert check("Write", {"file_path": str(sec), "content": content}) is None


def test_write_closing_a_new_entry_is_blocked(sec):
    content = findings_doc(("a1", "accepted-risk"), ("c3", "false-positive"))
    assert check("Write", {"file_path": str(sec), "content": content}) == MESSAGE


def test_write_closing_with_changed_closure_kind_is_blocked_only_if_new(sec):
    # c3 was already closed: re-writing it as accepted-risk is not a new closure
    content = findings_doc(("a1", "open"), ("b2", "proposed-false-positive"), ("c3", "accepted-risk"))
    assert check("Write", {"file_path": str(sec), "content": content}) is None


def test_write_unparseable_content_fails_closed(sec):
    assert check("Write", {"file_path": str(sec), "content": '{"findings": [ "status": '}) == MESSAGE


@pytest.mark.parametrize("old,new", [
    ('"proposed-false-positive"', '"false-positive"'),
    ("proposed-", ""),
    ('"open"', '"accepted-risk"'),
    ('"proposed-', '"'),
    ('"open"', '"false\\u002dpositive"'),
    ('"open"', '"accepted\\u002drisk"'),
    ('"status": "open"', '"status": "false-positive"'),
])
def test_edit_bypasses_are_closed(sec, old, new):
    assert edit(sec, old, new) == MESSAGE, (old, new)


def test_edit_honours_replace_all(sec):
    assert edit(sec, '"proposed-false-positive"', '"accepted-risk"', replace_all=True) == MESSAGE
    # dropping the status key makes the open findings disappear: blocked
    assert edit(sec, '"status"', '"state"', replace_all=True) == MESSAGE


def test_edit_allowed_cases(sec):
    assert edit(sec, '"open"', '"fixed"') is None
    assert edit(sec, '"proposed-false-positive"', '"open"') is None
    assert edit(sec, '"why"', '"because"') is None  # file already holds a closed entry (c3)
    assert edit(sec, "no such text", "x") is None


def test_edit_unreadable_file_fails_closed(tmp_path):
    missing = tmp_path / "security.json"
    assert edit(missing, "a", "b") == MESSAGE


def test_edit_result_not_json_fails_closed(sec):
    assert edit(sec, '"findings": [', '"findings": ') == MESSAGE


def test_multiedit_applies_sequentially(sec):
    steps = [{"old_string": '"open"', "new_string": '"zzz"'},
             {"old_string": '"zzz"', "new_string": '"accepted-risk"'}]
    assert check("MultiEdit", {"file_path": str(sec), "edits": steps}) == MESSAGE
    # the intermediate "zzz" alone is an unknown status: blocked too
    assert check("MultiEdit", {"file_path": str(sec), "edits": steps[:1]}) == MESSAGE
    fine = [{"old_string": '"open"', "new_string": '"zzz"'}, {"old_string": '"zzz"', "new_string": '"fixed"'}]
    assert check("MultiEdit", {"file_path": str(sec), "edits": fine}) is None
    assert check("MultiEdit", {"file_path": str(sec), "edits": "garbage"}) == MESSAGE


def test_symlink_to_security_json_is_judged_by_target(sec, tmp_path):
    link = tmp_path / "f.json"
    link.symlink_to(sec)
    assert check("Write", {"file_path": str(link), "content": findings_doc(("a1", "accepted-risk"))}) == MESSAGE
    assert edit(link, '"open"', '"accepted-risk"') == MESSAGE
    assert edit(link, '"open"', '"fixed"') is None


def test_relative_path_uses_payload_cwd(sec):
    out = check("Edit", {"file_path": "security.json", "old_string": '"open"', "new_string": '"accepted-risk"'},
                cwd=str(sec.parent))
    assert out == MESSAGE


def test_garbage_input_allows():
    assert check("Write", None) is None
    assert check("Write", {"file_path": PATH}) is None
    assert check("Read", {"file_path": PATH}) is None
    assert check("Write", {"file_path": "x.txt", "content": 5}) is None


# ---- disappearing findings, unknown statuses, id renames --------------------------

def test_open_finding_disappearing_is_blocked(sec):
    content = findings_doc(("b2", "proposed-false-positive"), ("c3", "false-positive"))
    assert check("Write", {"file_path": str(sec), "content": content}) == MESSAGE


def test_closed_finding_may_disappear(sec):
    content = findings_doc(("a1", "open"), ("b2", "proposed-false-positive"))
    assert check("Write", {"file_path": str(sec), "content": content}) is None


@pytest.mark.parametrize("status", [None, "", "closed", "wontfix", "resolved", 3, True,
                                    ["accepted-risk"], {"v": "accepted-risk"}, ["open"]])
def test_status_must_stay_an_assistant_status(sec, status):
    content = findings_doc(("a1", status), ("b2", "proposed-false-positive"), ("c3", "false-positive"))
    assert check("Write", {"file_path": str(sec), "content": content}) == MESSAGE


def test_new_entry_with_unknown_status_is_blocked(sec):
    content = findings_doc(("a1", "open"), ("b2", "proposed-false-positive"), ("c3", "false-positive"),
                           ("d4", "ignored"))
    assert check("Write", {"file_path": str(sec), "content": content}) == MESSAGE


def test_assistant_statuses_allowed(sec):
    for st in ("open", "fixed", "proposed-false-positive"):
        content = findings_doc(("a1", st), ("b2", st), ("c3", "false-positive"), ("d4", st))
        assert check("Write", {"file_path": str(sec), "content": content}) is None, st


def test_status_removed_by_edit_is_blocked(sec):
    assert edit(sec, '"id": "a1",\n      "status": "open",', '"id": "a1",') == MESSAGE


def test_rename_onto_closed_id_is_blocked(sec):
    # a1 (open) renamed to c3, which is already closed
    assert edit(sec, '"id": "a1",\n      "status": "open"', '"id": "c3",\n      "status": "false-positive"') == MESSAGE
    content = findings_doc(("c3", "false-positive"), ("b2", "proposed-false-positive"), ("c3", "false-positive"))
    assert check("Write", {"file_path": str(sec), "content": content}) == MESSAGE


def test_rename_onto_closed_id_with_a_new_open_twin_is_blocked(sec):
    # the original open entry is renamed onto a closed id, and a fresh a1 keeps the count
    content = findings_doc(("a1", "open"), ("b2", "proposed-false-positive"), ("c3", "false-positive"),
                           ("c3", "false-positive"))
    assert check("Write", {"file_path": str(sec), "content": content}) == MESSAGE


# ---- Bash (Review Focus 4) ----------------------------------------------------

BLOCKED_BASH = [
    "sed -i 's/open/accepted-risk/' security.json",
    "sed -i 's/\"status\": \"open\"/\"status\": \"x\"/' .cta/builds/x/security.json",
    "sed -i 's/proposed-false-positive/false-positive/' security.json",
    "sed -i 's/proposed-//' security.json && echo status",
    "sed -i.bak 's/a/b/' security.json # status",
    "sed -ni 's/a/b/p' security.json # status",
    "echo '{\"status\": \"accepted-risk\"}' > security.json",
    "echo '\"status\": \"x\"' >> builds/security.json",
    "echo '{\"status\":\"x\"}' >security.json",
    "python3 -c \"import json; d=json.load(open('security.json')); d[0]['status']='accepted-risk'\"",
    "python -c \"open('security.json','w').write('status')\"",
    "python3 - <<'EOF'\nimport json\np='security.json'\nd=json.load(open(p))\nd['status']='x'\njson.dump(d, open(p,'w'))\nEOF",
    "cp /tmp/new.json .cta/builds/x/security.json", "mv /tmp/new.json .cta/builds/x/security.json",
    "sed -i 's/open/fixed/' .cta/builds/x/*.json", "cd .cta/builds/x && sed -i 's/a/b/' sec*.json",
    "sed -i 's/propos.d-//' security.json", "perl -pi -e 's/a/b/' security.json",
    "perl -i.bak -pe 's/a/b/' .cta/builds/x/security.json", "ln -sf ../x/security.json f.json",
    "ln -s /tmp/y.json /w/security.json", "rsync /tmp/n.json .cta/builds/x/security.json",
    "dd if=/tmp/n.json of=security.json", "install -m 644 /tmp/n.json security.json",
    "sed -i 's/a/b/' *.json", "echo x | tee .cta/builds/x/sec*.json", "cat n > .cta/builds/x/security.json",
    "node -e \"require('fs').writeFileSync('security.json','{}')\"",
    "python3 -c \"import pathlib; pathlib.Path('security.json').write_text('{}')\"",
    "echo '[]' >| security.json",
    "jq '.[0].status = \"accepted-risk\"' security.json > tmp && mv tmp security.json",
    "jq '.[0].status = \"x\"' security.json | sponge security.json",
    "cat patch | tee security.json # status",
    "echo status | tee -a security.json",
    "cp /tmp/new security.json # status",
    "mv /tmp/status.json security.json",
    "echo accepted-risk security.json",
    "grep false-positive security.json",
    "echo $(echo accepted-risk > security.json)",
    "sec\"urity\".json; sed -i s/status/x/ sec\"urity\".json",
    "sed -i 's/a/b/' secu\\rity.json # status",
    "echo '{\"st'\"atus\"'\": 1}' > security.json",
    "awk '{print}' security.json > out.json; status=1 mv out.json security.json",
    "bash -c \"sed -i 's/a/b/' security.json # status\"",
    # in-place edits, find -exec, redirects and tee aimed under .cta/ or a builds/ folder
    "sed -i 's/a/b/' .cta/builds/x/notes.md", "perl -i -pe 's/a/b/' builds/x/y.txt",
    "ex -sc '%s/a/b/|x' .cta/builds/x/record", "vim -es -c '%s/a/b/' -c wq .cta/x",
    "ed -s .cta/builds/x/record < script", "patch .cta/builds/x/record < p.diff",
    "patch -p1 -d .cta < p.diff", "git apply --directory=.cta x.patch",
    "find .cta -name '*.json' -exec sed -i s/a/b/ {} +", "find builds -type f -execdir sh -c 'x' \\;",
    "echo x > .cta/builds/x/notes", "echo x >> projects/app/builds/2026-01-02-login/review.md",
    "echo x | tee builds/x/f", "sed -i 's/a/b/' .c*/builds/x/f", "sed -i 's/a/b/' ./*/builds/x/f",
    "link .cta/builds/x/security.json /tmp/l", "cp -l security.json /tmp/h", "cp --link security.json h",
    "cp -al .cta/builds/x/security.json h", "rm .cta/builds/x/security.json", "truncate -s 0 security.json",
    "mv .cta/builds/x/notes.md /tmp/n", "cp /tmp/n .cta/builds/x/",
    "cp -al builds/x /tmp/y", "cp -a -l .cta/builds /tmp/y", "cp --link -r builds /tmp/y",
]


@pytest.mark.parametrize("command", BLOCKED_BASH)
def test_closure_guard_blocks_bash_writes(command):
    assert check("Bash", {"command": command}), command


ALLOWED_BASH = [
    "cat security.json",
    "jq '.findings[] | select(.status == \"open\")' security.json",
    "jq -r '.findings[].status' .cta/builds/x/security.json | sort | uniq -c",
    "grep -c proposed-false-positive security.json",
    "grep status security.json",
    "ls -l security.json",
    "echo '{}' > other.json && sed -i s/a/b/ notes.txt # status",
    "git add security.json && git commit -m 'record findings'",
    "echo false-positive > notes.txt",
    "sed -i 's/accepted-risk/x/' README.md",
    "wc -l security.json",
    "jq '.findings[]' security.json > /tmp/x.json",
    "jq '.[0].status' .cta/builds/x/security.json > /tmp/out.txt && cat /tmp/out.txt",
    "python3 -c \"import json; print(json.load(open('security.json'))['findings'])\"",
    "python3 -c \"import json; d=json.load(open('security.json')); print(len(d))\"",
    "sed -n '1,5p' security.json", "cp security.json /tmp/backup.json", "sed -i 's/a/b/' notes.json",
    "cp /tmp/a.json /tmp/b.json", "echo hi > out.json",
    "cat .cta/builds/x/notes.md", "sed -n p .cta/x", "find .cta -name x", "grep -r x builds/",
    "ls builds/", "sed -i 's/a/b/' src/app.py", "echo hi > /tmp/out", "cp .cta/builds/x/notes.md /tmp/n",
]


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_closure_guard_allows_reads_and_unrelated(command):
    assert check("Bash", {"command": command}) is None, command


def test_cwd_inside_a_builds_folder_protects_relative_paths(tmp_path):
    folder = tmp_path / ".cta" / "builds" / "x"
    assert check("Bash", {"command": "sed -i 's/a/b/' notes.txt"}, str(folder))
    assert check("Bash", {"command": "echo x > notes.txt"}, str(folder))
    assert check("Bash", {"command": "sed -i 's/a/b/' notes.txt"}, str(tmp_path)) is None
    assert check("Bash", {"command": "cat notes.txt"}, str(folder)) is None


def test_proposed_via_bash_write_is_still_blocked():
    # the assistant edits findings with Write/Edit, never with a shell write
    assert check("Bash", {"command": "jq '.[0].status=\"proposed-false-positive\"' security.json > t && mv t security.json"})


# ---- hook process -----------------------------------------------------------------

def run_hook(payload):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True)


def test_hook_exit_codes():
    blocked = run_hook({"tool_name": "Write", "tool_input": {"file_path": PATH, "content": doc("accepted-risk")}})
    assert blocked.returncode == 2 and "only Matt closes findings" in blocked.stderr
    assert run_hook({"tool_name": "Write", "tool_input": {"file_path": PATH, "content": doc("open")}}).returncode == 0
    assert run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}).returncode == 0
    bad = subprocess.run([sys.executable, str(HOOK)], input="nope", capture_output=True, text=True)
    assert bad.returncode == 0


def test_matt_only_matches_findings_module():
    import findings
    assert finding_guard.MATT_ONLY == findings.MATT_ONLY


def test_non_string_status_in_current_file_does_not_crash(tmp_path):
    path = tmp_path / "security.json"
    path.write_text(json.dumps({"findings": [{"id": "a", "status": ["x"]}, {"id": "b", "status": "open"}]}))
    assert edit(path, '"open"', '"fixed"') == MESSAGE  # a1's non-string status is a violation


@pytest.mark.parametrize("payload,code", [
    ({"tool_name": "Write", "tool_input": {"file_path": PATH, "content": "{}"}}, 2),
    ({"tool_name": "Edit", "tool_input": {"file_path": "/x/Security.JSON"}}, 2),
    ({"tool_name": "Bash", "tool_input": {"command": "cat security.json"}}, 2),
    ({"tool_name": "Write", "tool_input": {"file_path": "notes.txt", "content": "x"}}, 0),
    ({"tool_name": "Bash", "tool_input": {"command": "ls"}}, 0),
])
def test_unexpected_error_fails_closed_for_findings_files(payload, code, monkeypatch, capsys):
    import io

    def boom(*_a, **_k):
        raise TypeError("x")

    monkeypatch.setattr(finding_guard, "check", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as info:
        finding_guard.main()
    assert info.value.code == code
