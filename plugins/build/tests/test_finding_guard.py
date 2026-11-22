import json
import subprocess
import sys
from pathlib import Path

import pytest

import finding_guard
from finding_guard import check

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "finding_guard.py"
PATH = ".cta/builds/x/security.json"


def doc(status):
    return json.dumps({"findings": [{"id": "ab", "status": status, "reason": "why"}]})


# ---- Write / Edit / MultiEdit ----------------------------------------------

@pytest.mark.parametrize("status", ["false-positive", "accepted-risk", " False-Positive ", "ACCEPTED-RISK"])
def test_closure_guard_blocks_write(status):
    reason = check("Write", {"file_path": PATH, "content": doc(status)})
    assert reason == 'only Matt closes findings; set "proposed-false-positive" with your reasoning'


@pytest.mark.parametrize("status", ["open", "fixed", "proposed-false-positive"])
def test_closure_guard_allows_proposed(status):
    assert check("Write", {"file_path": PATH, "content": doc(status)}) is None


def test_write_to_other_file_is_not_inspected():
    assert check("Write", {"file_path": "notes.md", "content": doc("accepted-risk")}) is None
    assert check("Write", {"file_path": "security.json.bak", "content": doc("accepted-risk")}) is None


def test_path_suffix_match_and_windows_separators():
    assert check("Write", {"file_path": "C:\\p\\Security.JSON", "content": doc("accepted-risk")})
    assert check("Write", {"file_path": "/x/my-security.json", "content": doc("accepted-risk")})


def test_escaped_status_in_json_is_decoded():
    content = '{"findings": [{"status": "false\\u002dpositive"}]}'
    assert check("Write", {"file_path": PATH, "content": content})


def test_edit_fragments():
    block = ['"status": "false-positive"', '"status":"accepted-risk",', '"false-positive"',
             '  "status"  :  "accepted-risk"']
    for frag in block:
        assert check("Edit", {"file_path": PATH, "old_string": "x", "new_string": frag}), frag
    for frag in ['"status": "proposed-false-positive"', '"status": "open"', 'proposed-false-positive']:
        assert check("Edit", {"file_path": PATH, "old_string": "x", "new_string": frag}) is None, frag


def test_edit_only_new_string_counts():
    assert check("Edit", {"file_path": PATH, "old_string": '"status": "accepted-risk"',
                          "new_string": '"status": "open"'}) is None


def test_multiedit_any_edit_blocks():
    edits = [{"old_string": "a", "new_string": '"status": "open"'},
             {"old_string": "b", "new_string": '"status": "accepted-risk"'}]
    assert check("MultiEdit", {"file_path": PATH, "edits": edits})
    assert check("MultiEdit", {"file_path": PATH, "edits": edits[:1]}) is None
    assert check("MultiEdit", {"file_path": PATH, "edits": "garbage"}) is None


def test_garbage_input_allows():
    assert check("Write", None) is None
    assert check("Write", {"file_path": PATH}) is None
    assert check("Write", {"file_path": PATH, "content": 5}) is None
    assert check("Read", {"file_path": PATH}) is None


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
    "python3 - <<'EOF'\nimport json\np='security.json'\nd=json.load(open(p))\nd['status']='x'\nEOF",
    "jq '.[0].status = \"accepted-risk\"' security.json > tmp && mv tmp security.json",
    "jq '.[0].status = \"open\"' security.json > tmp",
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
]


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_closure_guard_allows_reads_and_unrelated(command):
    assert check("Bash", {"command": command}) is None, command


def test_proposed_via_bash_write_is_still_blocked():
    # the assistant edits findings with Write/Edit, never with a shell write
    assert check("Bash", {"command": "jq '.[0].status=\"proposed-false-positive\"' security.json > t"})


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
