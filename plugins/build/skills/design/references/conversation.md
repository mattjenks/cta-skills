<!-- Adapted from obra/superpowers skills/brainstorming/SKILL.md (MIT) -->

# Design conversation

Read before the first question. People often have not finished working out what they want; good questions
help them think. When you understand the why, you make the hundred unmentioned decisions the way they would.

## What do you actually know?

- Everything that matters is in the request ("rename this flag"): do it, say what you did. No design.
- Something non-trivial is missing: start the conversation.

## First message

- **They have said what they want** (a spec, a ticket, a detailed request): about 200 words. Echo the request in
  your words (what, for whom, why as far as they said it), add what you found that bears on it (how the
  relevant parts work today, what the change touches), and flag anything that would change the ask: a
  constraint, a conflict, a cheaper path. End with one line inviting correction. If the why is missing, ask
  it as one open question with nothing to pick from.
- **They have not:** one open question about the biggest unsettled thing, with why it matters to what you build.

## The conversation

- Ask only when the answer would change what gets built and neither the request nor the repo answers it.
  Otherwise state your call and your reason as a proposal they can correct.
- One question at a time, plain language, their vocabulary. No process jargon.
- Until the why is clear, ask open questions with no example answers; options steer. After that, when a
  decision has nameable choices, sketch each with its trade-off and your pick. On "just guess", propose.
- Build each question on their last answer or on something you found, so it helps them think through a case
  they may have missed ("two members joined this month; do they vote mid-round?").
- Choices about how it is built (language, libraries, platform): someone who raises trade-offs wants options
  and your pick; someone who talks outcomes hands you the how, so decide and state each in a line. Existing
  work wins: build on what the repo already uses. Mark every such choice as your call.
- Do recon when it helps: deeper into the code, the owner's knowledge base, or the web. Say what you looked for.

## Ground to cover (territory, not a script)

What kind of thing this is; why now and what success looks like; goals, non-goals, anti-goals (what would
make it a failure even if it works); prior art; current state and what was tried; the details they care about.

## Play it back

As soon as you understand one part, describe it in 200 to 300 words and return to questions about the next
part. Only what they said goes in as theirs; anything you filled in is your proposal with a reason. End each
chunk by asking what is wrong or missing. For anything they will look at, add a text sketch.

## Size the work

Say how big it is in plain words once an approach is picked. A small change gets a short design (what you
covered together, a line or two per point). A project gets the full design, and its accepted gaps. If it grows
mid-task, say so and step up. If it is really several projects, agree an order and design them one at a time.

## Red flags

| Thought | Reality |
|---|---|
| "I'll offer a menu of what they might want" | Options steer. Ask them to describe it first. |
| "I'll fill in sensible defaults" | Good. Say them out loud; an unheard default cannot be rejected. |
| "They said sounds good to the idea" | Approval covers what you showed. An unwritten design is not approved. |
| "A quick spike will do, I will keep it" | A spike is throwaway. Keeping it is a new request, back through this gate. |
