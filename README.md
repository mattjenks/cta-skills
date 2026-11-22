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

## Credits

Parts of CTA are adapted from [Cole Medin's skills](https://github.com/coleam00/skills) and
[superpowers](https://github.com/obra/superpowers). See `NOTICE`. Licensed under MIT.
