## Parallel tool-calls crashed memory edits and deleted the wrong memory (Phase 6, cases 32–35)


Editing a memory (*"I changed my mind — ask me each time instead"*, meant to drop
the sorting preference) crashed — and worse, kept deleting memories on each retry.

```
memories before:  [m1 = "project folder", m2 = "prefers ls sorted by size"]

$ doit "I changed my mind — ask me each time instead"
· forgot m2
doit: error: litellm.BadRequestError: OpenAIException - An assistant message with
'tool_calls' must be followed by tool messages responding to each 'tool_call_id'.
The following tool_call_ids did not have response messages: call_xEetwmU...

$ doit "I changed my mind — ask me each time instead"     <- user retries
· forgot m1                                                <- now forgets the WRONG memory
doit: error: ... tool_call_ids did not have response messages ...

memories after the cascade:  []   (both facts gone)
```
*(logs/phase6/behavior_issue.txt)*

**Root cause.** `gpt-4o-mini` bundled `forget` + `remember` as **two** `tool_calls` in
a single assistant message. Our controller answers one
Decision per call, so it acted on the first tool-call and replayed the whole
assistant message on the next iteration — leaving the second `tool_call`
unanswered. OpenAI's tool protocol requires every `tool_calls` entry to be followed
by a matching `tool` response; the orphaned id was rejected with a 400. Because
`forget` had already mutated the store **before** the crash, each retry silently
deleted another memory (`[m1,m2] → [m1] → []`), and id recycling meant the
surviving fact could later be forgotten under the wrong id.

**The fix.** `llm._dump_single_tool_call` drops the sibling tool-calls before the
message is replayed, so no orphaned id is ever sent. the dropped action (e.g. the
`remember` half of an edit) simply re-enters on the next loop iteration, once the
model sees the updated memory state. We chose this — keeping the invariant "one LPU
call = one Decision", unchanged since Phase 1 — over restructuring `Decision` into a
list of calls, which would have broken adapter interchangeability (the prompted
adapter can never bundle). Verified crash-free afterward:

```
$ doit "my favourite folder was changed to /prompts"
· forgot m2
· remembered [m2]: the user's favourite folder is /prompts
(memories.json: m1 kept, m2 correctly updated -- no crash, no wrong deletion)
```
*(logs/phase6/good_interaction_memo.txt)*

**Lesson.** A model may pack several tool-calls into one message even when the
controller is built around one-decision-per-turn. If the loop replays that message
without answering every call, the provider rejects the whole request — and any tool
that already ran (like `forget`) leaves a partial, destructive side effect behind.
Normalising to a single tool-call before replay keeps the one-Decision invariant and makes edits atomic from the user's point of view.
