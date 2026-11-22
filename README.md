# CTA — Chief Technology Assistant

CTA is a prescriptive, Claude Code-specific system of skills and hooks for one loop:
**plan → build → deploy → monitor → learn**.

It is opinionated by design: one way through the loop, enforced by hooks rather than suggested.
The assistant's voice is a swappable persona. The bundled one is `default` ("CTA").

## Install

```text
/plugin marketplace add mattjenks/cta-skills
/plugin install core@cta
```

Skills are invoked as `/core:<skill>`.

## Configuration

Personal settings live outside this repository, in `~/.config/cta/config.toml`:

```toml
persona = "default"            # which persona to load
context = ["USER.md"]          # files injected at session start, in order
kb = "~/path/to/knowledge-base" # where context files and personas are resolved
```

If the file is missing or unreadable, CTA starts with the default persona.

## Contributing / releases

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`,
`docs:`, `chore:`; `!` or a `BREAKING CHANGE:` footer for breaking changes). On every push to `main`,
release-please keeps a release PR open that bumps each plugin's version (in its `plugin.json` and its
`.claude-plugin/marketplace.json` entry) and its `CHANGELOG.md`. Merging that PR tags the release.

Pull requests need the `tests` check (the CI workflow) to pass before merging to `main`.

## Credits

Parts of CTA are adapted from [Cole Medin's skills](https://github.com/coleam00/skills) and
[superpowers](https://github.com/obra/superpowers). See `NOTICE`. Licensed under MIT.
