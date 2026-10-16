# Standing orders

How to work in this repository. Project facts (layout, branches, commands, the data posture) live
in the project rule beside this file, `raff.md`.

## The three habits

1. **Name the destination out loud before you act:** which branch the work is cut from and which
   branch it lands on. Ambiguity here is expensive to undo, and it is caught by saying the
   sentence, not by being careful.
2. **Say what you actually did, not what you intended.** A push that reports success can still
   have gone somewhere unintended. Check with `git ls-remote`, not with the command's own output.
3. **Confirm before anything irreversible or visible to other people:** deleting a remote branch
   or tag; force-pushing; rewriting shared history; dropping or migrating a real database;
   creating a repository; changing CI or branch protection; any write to GitHub; anything that
   reaches production. Say what will change and where, get a yes, then do it. Once, not per field.

## Size the job, then stop once

Every piece of work gets a **tier**, stated in one line the owner can override:

| Tier | What | The one stop |
|---|---|---|
| 1 | small, low-risk, reversible | none. Say what you will do, then do it |
| 2 | a normal feature, fix, or refactor | one message after Understand: the summary, the outcome checklist, the branch sentence |
| 3 | high-risk, hard to reverse, or architecture-touching | the same message, plus a decision entry in the knowledge base |

**The hard floor:** auth, authorization, payments, secrets, data migration, a public API or
contract, a security control, cross-module architecture. Any of these is Tier 3 and cannot be
tiered down. Round up when unsure.

After the yes, **build uninterrupted.** Pause only for the stop-list: a Tier-3 area touched
unexpectedly · a new dependency · a schema or migration change · data deletion · anything reaching
production or an unfamiliar remote · two failed attempts at the same thing · scope growing past the
agreed boundary. Everything else waits for the hand-back. Before any autonomous run, commit a
checkpoint: git is the undo, not the session's own checkpoints. Task commits stay on task-owned
paths; files dirty before the task belong to the owner.

## What counts as done

- **Deterministic checks carry correctness.** A model's confidence, however high, is not evidence.
  Run `bash .claude/tools/verify.sh` before claiming anything builds; CI is the only neutral check.
- **A green counts only if the check can go red.** A check that has never failed is suspect, and
  `verify.sh --canary` must fail. A flaky result is not evidence: quarantine it, do not cite it.
- **Evidence settles a claim, in this order:** a deterministic failing check or reproducer · your
  own recompute · a spec line · model judgment alone. A citation never settles a claim by itself.
- **Say the direction delta:** what shipped, in product terms, versus what was asked. A perfectly
  built wrong feature passes every check.
- **Verify after a build:** `bash .claude/tools/verify.sh --full` green, then a local run of the
  app with `/test-guide`, recording what was actually seen. Independent code review is not part of
  this project's loop; the project rule says so and why.
- **For critical logic a human confirms the expected values.** A test must never enshrine
  current-buggy behaviour.

## What is enforced, and what is advice

Everything in this folder is advice except four hooks. `guard-secrets` blocks a secret **value**
written through Edit or Write. `guard-commands` blocks the destructive commands on its list, which
starts empty and grows from incidents. `verify-on-finish` blocks a turn that weakened, skipped, or
deleted a test since the baseline of the task this session carries. `resume-brief` re-reads that
same task's brief after a compaction. Both read `working/active-tasks/<session id>`, which
`baseline.sh seal` writes at the owner's yes; with no task bound, the first compares against `HEAD`
and the second restores the newest task brief and calls it a guess. None of these four hooks sees a
browser, an MCP call, chat, or a shared folder. **Rules and hooks load at session start: restart
the session after changing either.**

One more thing is mechanical, and it is a check rather than a hook: `verify.sh` refuses a knowledge
base whose durable pages lack the required header, whose checked references do not resolve, or whose
README states a count the tree contradicts (when a drift list is configured). It decides structure,
never whether a claim is true.

## Where things live

| Path | What it is |
|---|---|
| `.claude/` | the harness: rules, skills, hooks, tools, settings. Committed. Read every session |
| `docs/knowledge-base/` | facts with evidence, point-in-time, committed |
| `working/` | **yours, local, disposable, never committed.** Status, handoffs, task briefs, scratch. Deleting it must lose nothing durable. It is per checkout: a linked worktree starts without it, so a task agreed in one does not travel to another |

## Capture, posture, memory

- **Anything noticed and not acted on goes into `99-pending.md` in the same turn**, one line, with
  enough context to act later. Never into `working/`; that is a slower way of losing it.
- **Data posture** is `demo` or `production`, declared in the project rule. In demo, security and
  robustness hardening are non-blocking follow-ups, every shortcut is a `99-pending.md` line tagged
  `demo-debt`, and the flip to production waits until that list is empty or owner-waived. In
  production they block.
- **Auto memory is scratch.** Anything durable in it is promoted to a rule or a knowledge-base page
  through `/record`. Anything that is status goes to `working/`.
