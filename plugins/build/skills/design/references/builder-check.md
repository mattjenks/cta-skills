<!-- Adapted from obra/superpowers skills/brainstorming/builder-check-prompt.md (MIT) -->

# Builder check

Dispatch one fresh subagent with the prompt below, on **sonnet** (see `../../implement/references/models.md`),
once the written design exists. Fill in the domain and the document path. Never dispatch it on a more capable
model than the map names.

```text
You are a talented [DOMAIN, e.g. "software engineer"]. You have been handed a design document and asked to
put together a plan to build what it describes. You will not be able to talk to the person who wrote it.

Read [DOCUMENT_PATH].

Report only the questions you would still need answered before you could plan this well: places where you
would have to guess and a wrong guess would matter. For each, give the question and why the answer changes
the plan. Rank them by importance.

Skip anything the document explicitly leaves to the builder, and anything you could reasonably decide
yourself. Skip nitpicks about wording.

If nothing important is left, say "nothing important left".
```

## Handling the answer

Tell the owner you are writing the design up and that a reviewer will read it first, so you may come back once
with a few questions. Sort what returns into three piles:

- **Answered already** by the conversation or the project: put the answer in the document.
- **Minor:** a sensible builder could settle it without changing what gets built. Settle it and mark it in the
  document as your call.
- **The owner's:** only the owner can answer it, and the answer changes what gets built. Bring these in one
  message, most important first. Update the document with the answers, then hand it over with a short list of
  the calls you made so they can check them while reading.

That is the only round of questions the check produces. Without a subagent tool, read the document yourself as
that builder.
