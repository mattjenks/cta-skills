# Templates

Everything under `templates/` is copied to the target folder with the same relative path.

| File | Purpose |
|---|---|
| `README.md` | Layout, precedence of the documents, and filing rules |
| `BOUNDARIES.md` | Freely, ask-first and never lists for the assistant; highest precedence |
| `SOUL.md` | Voice, accuracy, judgment and habits; placeholders to fill in |
| `USER.md` | Who the owner is; placeholders to fill in |
| `PREFERENCES.md` | Learned corrections and confirmed approaches |
| `DECISIONS.md` | Decision log, newest first |
| `projects/README.md` | The project standard: `design.md`, `reqs.md`, `plan.md`, `backlog.md` and `builds/<YYYY-MM-DD>-<topic>/` with `progress.md`, `security.json`, `retro.md` |
| `.markdownlint-cli2.jsonc` | markdownlint rules (line length off, duplicate headings allowed across siblings) |
| `.github/workflows/lint.yml` | Job `markdownlint` on pull requests and pushes to `main` |
| `.github/workflows/secret-scan.yml` | Job `gitleaks` with full history on pull requests and pushes to `main` |

## Workflows

Both workflows run with `permissions: contents: read` and pin every action to a full commit SHA with
the release tag in a trailing comment. To update a pin, resolve the new tag to a commit with
`gh api repos/<owner>/<repo>/git/ref/tags/<tag>` (dereference annotated tags through
`git/tags/<sha>`), never copy a SHA from a blog post. The gitleaks action may need a license key
when the repository belongs to an organization; a personal account needs none.

## What the script will not do

- It never overwrites a file that exists in the target.
- It does not commit, create a remote or push; the skill asks before each.
- It never edits a config file that is not valid TOML.
