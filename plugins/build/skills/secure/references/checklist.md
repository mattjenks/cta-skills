<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md (MIT) -->

# Security checklist

## Reviewer prompt

Dispatch on opus (`../../implement/references/models.md`). Pass paths, never pasted content.

```text
You are doing a security review of one branch in [REPO_PATH].

Read [PACKAGE_PATH] (the diff and the design context) and [SECURITY_JSON_PATH] (what scanners already
found: do not repeat those). Open the changed files and the code they call; the diff alone hides
callers. Check every item below against the code this branch adds or changes. Report only issues you can
trace to a concrete input an attacker or a malformed file could control. Do not edit files.

For each finding: severity (Critical, High, Medium, Low), file and line, the exploit in one sentence, and
the smallest fix. End with `Verdict: CLEAN` or `Verdict: FINDINGS` and the counts.
```

## The nine checks

1. **Injection**: SQL, NoSQL, template, header, log, argument injection; string-built queries or commands.
2. **Authn and authz**: a missing or bypassable check, a check on the client only, an object reached by id
   without an owner check, a default credential, a token that never expires.
3. **Secrets**: keys, tokens or passwords in code, tests, fixtures, config or logs; secrets in URLs.
4. **Deserialization**: pickle, yaml.load, unsafe `eval`/`exec`, object revival of untrusted input.
5. **Path traversal**: user input in a file path without normalizing and confining it; archive extraction
   paths; symlink following.
6. **SSRF**: a server fetching a user-supplied URL without an allowlist; redirects, private address ranges.
7. **Unsafe shell**: `shell=True`, string-built commands, unquoted variables, user input as an option.
8. **Crypto misuse**: home-made crypto, weak or unsalted hashes for passwords, ECB, static IVs, `random`
   for tokens, disabled certificate checks.
9. **Prompt injection**: untrusted text (web pages, files, issue bodies, tool output) reaching a model
   that can act, without a confirmation step; tool output treated as instructions; hooks and skills that
   run content they read.

## Scanner notes

- Required: `semgrep` and `gitleaks` (`brew install semgrep gitleaks`). A repo with manifests also needs the
  auditors `scan.py` names: `pip-audit` (`uv tool install pip-audit`), `osv-scanner` (`brew install
  osv-scanner`), `npm`. `secure.py` prints the command; the assistant never installs a tool unasked.
- Semgrep's `p/default` ruleset is fetched from the registry on the first run, so that run needs network
  access (and may be slow). Offline, the scan fails closed: STOP and tell the owner; do not substitute
  another ruleset.
- A scan error is never "no findings". Exit 3 from `secure.py` means the pass has not run.
