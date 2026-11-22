# Eval cases

Every skill ships at least 2 cases under `skills/<name>/evals/<case>/`, in the layout `claude plugin eval`
reads. Evals run locally, never in CI: they are billed model runs.

## Layout

```text
evals/
  case-name/            lowercase letters, digits, hyphens; not results, mocks, node_modules, files
    prompt.md           settings block, then the prompt as the user would type it
    case.yaml           schema_version "1.1", name (= folder), expected_outcome
    graders/
      01-few-words.md   one verifiable statement per file
```

`prompt.md` settings block (an unknown key makes the case fail to load; keep free text out of it):

```markdown
---
tags: [my-skill]
max_turns: 15
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill]
---

The user's prompt.
```

`case.yaml`:

```yaml
schema_version: "1.1"
name: case-name
expected_outcome: |
  What a good result looks like.
```

Grader file (the CLI ignores a file without the header):

```markdown
---
type: llm
focus: trace
weight: 1
---

The answer states that exit code 2 blocks.
```

Word each grader about the result itself, one fact per file, so a pass rate is the share of graders met.
A case with no grader does not load. Input files go in `files/` with a `place-files.sh` scaffold named in
`case.yaml` under `context: scaffold_script:` and run with `--scaffold`.

## Choosing cases

One case for the main task, one for a near-miss, a pressure case or the question users actually ask. Give
`allowed_tools` only what the case needs: question cases get read-only tools; cases that create files add
`Write, Edit` and need `--allow-tools Write,Edit`.

## Running

From the skill folder:

```bash
claude plugin eval . --runs 1 --trust-plugin --no-publish --allow-tools Write,Edit --json /tmp/out.json
```

It runs each case with the skill and without it (the baseline arm) and scores each grader. `--runs 1` keeps cost
down; `--case <glob>` runs one case; `--max-cost-usd` caps spend. Results land in `evals/results/`; that folder
is not committed. A case the baseline also passes tests nothing, so sharpen it. Record the with and without pass
rates when you finish.
