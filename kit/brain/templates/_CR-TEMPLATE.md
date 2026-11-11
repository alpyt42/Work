---
date: YYYY-MM-DD
time: "HH:MM"
type: cr
client: <client; delete for an internal project>
mission: <mission, or delete if not applicable>
project: <internal project, instead of client and mission; delete for a client mission>
title: <title>
participants: ["First Last", "First Last"]
provenance: "<tool or person, date, approximate duration>"
reliability: <good | medium | low>
written_by: "cr-reunion (<model>)"
---

# YYYY-MM-DD — <Title>

> Template for `<mission>/sources/YYYY-MM/YYYY-MM-DD-cr-<slug>.md` (`cr` = meeting minutes). Delete this instruction, the examples and any empty optional section. The minutes stay a dated, standalone source: they keep the facts, attributions, decisions, commitments, figures, dates, risks and changes needed to understand them. Each fact is stated once, in its section. The body, front matter excluded, holds at most 50 words per minute of meeting up to 30 minutes, then 20 per further minute, with 250 words always allowed and 2,000 never exceeded: a cap, not a target. For an internal project, the source sits in `projects/internal/<project>/sources/YYYY-MM/`, the front matter has `project:` instead of `client:` and `mission:`, and the link below reads `Project page:`. Context taken from memory (earlier minutes, registers) rather than from the transcript is set apart, under the marker line `_From memory._`.

Mission page: [<mission>](../../<mission>.md).

> <Reliability limit, only if it affects reading; delete otherwise.>

## Summary

<Two sentences, about 40 to 60 words: main outcome of the meeting, major decision or blocker, then the immediate next step. Do not copy the list of topics.>

## Key points

- **<Topic>:** <useful fact, position or figure>; <possible consequence>. <About 60 words per bullet, 90 at most: split a topic rather than lengthen it. Decisions and commitments go in their own sections, not here.>
- **<Topic>:** <fact attributed to the person concerned when it matters>.

## Decisions

- **<Taken | Rejected | To confirm>** — <worded choice> — <who decided or arbitrated>.

## Actions and follow-up

- **New** — <owner> — <verifiable outcome> — <announced due date, or due date to obtain>.
- **Follow-up · <ID>** — <change of owner, due date, state or blocker>.

## To follow

- <Unassigned lead or commitment> — next question or expected event: <…>.

## To check

- <Uncertainty that could change a name, an owner, a date, a figure, an exact identifier or a decision> — <timestamp if any>. <A mere mishearing goes to `state/glossary.md`.>

## Details

<Only if a technical, contractual or scope nuance is essential.>
