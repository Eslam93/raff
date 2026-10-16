---
title: How Raff is built - who decides what, the loop every step followed, and the guardrails
status: verified
as_of: 2026-10-16
last_verified: 2026-10-16
verification_method: Described from the harness files in .claude/, the step briefs, and the record of steps 0 to 7 in ../30-delivery/build-log.md
scope: The working method for this repository: roles, the per-step loop, the checks and hooks, and what the method does not cover
confidence: High for what the method is and what the hooks enforce, read from the harness itself. Medium for how well it would scale to a team, which was never tested
known_gaps: The method was used by one owner and one AI assistant over one day of building. No independent review was part of the loop (D-15), so defects the checks cannot see rely on the browser walks alone
supersedes: the 2026-09-20 wording, written for a reviewer of one submission; the method it describes is unchanged
reverify_when: The harness rules or hooks change, or the loop changes
---

# How Raff is built

Raff is built by an AI coding assistant working inside a
small harness of rules, hooks and checks (`.claude/`). This page says who decided what, the loop
every step followed, what is enforced mechanically, and where the method stops.

## Who decided what

**The owner decided the product.** Before any code, the owner wrote the product definition that
became `../10-product/product-spec.md`: the scope rule ("AI can expose and operate capabilities
that already exist; AI does not introduce new business workflows"), the circulation model, two
roles, one Copilot with three faces, the out-of-scope list, and the cut lines. During the build the
owner also decided:

| Decision | Where recorded |
|---|---|
| The stack and one container serving one origin | D-04 |
| Google sign-in, plus demo sign-in so anyone can try both roles | D-05 |
| Staff get both the staff and the analyst faces in one panel | D-06 |
| Models through OpenRouter; the default model choice was delegated | D-11, D-19 |
| Demo data from reader personas only, with no answer key or evaluation data | D-10 |
| ISBN lookup and covers added to scope | D-13 |
| Value order, stoppable after any step; publishing and deployment at the end | D-14 |
| No separate code-review stage | D-15 |
| The analyst's metric catalogue, and a charts library loaded on demand | D-20 |
| Step 8 designed rather than built | D-21 |
| One commit for the first publication, then normal history from `v0.1.0` | D-22, D-26 |
| Where the demo is deployed, and on which name | D-23 |
| Google sign-in open to any account, with the notices that requires | D-24 |
| The harness and this knowledge base ship with the code | D-16 |

**The assistant proposed and built.** It proposed the architecture and the step briefs, flagged
trade-offs (for example typed metric queries instead of generated SQL for the analyst, D-08, and
honest forecasting, D-09), built each step, and verified it. Every decision above was proposed with
its options and agreed explicitly before the build that depended on it.

## The loop every step followed

1. **A brief.** The step's outcome checklist in the form "given, when, then, verified by", the data
   model changes, and the exact API contract (types, endpoints, status codes, error codes). The
   owner approved it once; nothing was built before that approval.
2. **A parallel build.** The backend and the frontend (and, in step 3, the data generator) were built
   by separate AI builder sessions at the same time, each confined to its own folder and working
   from the same written contract, so the halves met at an agreed interface rather than at
   whatever one side happened to produce.
3. **Integration by the lead.** The full gate; a rebuild of the Docker stack; a browser walk of
   every checklist line against the real stack and data; for the Copilot, live turns against the
   real model. Anything the walk found was fixed with a regression test that was shown to fail
   first (see the "what went wrong" parts of `../30-delivery/build-log.md`).
4. **Records.** The README status, the decisions, the open items in `../99-pending.md`, and the
   step's entry in the build log, before the step counted as done. While the work ran, each step was
   committed in pieces (the backend, the web app, each fix with its test, the documentation); this
   repository is published as a single commit, so the build log carries that record instead.

## What is enforced mechanically

| Guard | What it does | Where |
|---|---|---|
| The gate | `bash .claude/tools/verify.sh --full`: harness checks plus backend lint, formatting, strict types and tests, and frontend lint, types, tests and build. A step is not done until it is green | `.claude/tools/verify.sh`, `.claude/tools/verify.project.sh` |
| A canary | `verify.sh --canary` must fail, and a planted lint error was shown to turn the gate red, so a green result means something | `.claude/tools/verify.sh` |
| Real-database tests | integration tests run against their own PostgreSQL database; with `REQUIRE_DB=1` a missing database fails the run instead of skipping it | `repo/backend/tests/integration/conftest.py` |
| Secret guard | a hook blocks writing a secret-shaped value into any file through the editing tools | `.claude/hooks/guard-secrets.*` |
| Test guard | a hook blocks ending a turn in which a test was weakened, skipped or deleted | `.claude/hooks/verify-on-finish.*` |
| Resume guard | after a context compaction, a hook restores the agreed brief, so the build continues from the agreement | `.claude/hooks/resume-brief.*` |

The hooks watch the assistant's editing tools and shells; they do not watch a browser or anything
outside the repository. That is stated in the harness rules and repeated here so the guard is not
overstated.

## How the AI inside the product was kept honest

The same principle applies to the Copilot the product ships: rules that matter are enforced in
code, not only in prompts. Identity comes from the session, never from the model; tool parameters
reject unknown fields; every number in a reply must appear in a lookup result; the model can only
propose a change, never make one (D-07). Tests use a scripted fake model so they run without a key
and cannot drift with a model's mood; the real model was then exercised live
(`../30-delivery/build-log.md`, step 4).

## Where the method stops

- **No independent review of the code** (D-15). Correctness rests on the gate and the browser
  walks. The record was reviewed, though: on 2026-09-20 two independent passes read the newest
  pages against the code before publishing and found 16 places where a claim did not match it,
  such as a wrongly cited file for search and an overstated Origin check. All were fixed. A third
  pass, after the deployment, found the stale claims a finished project leaves behind, such as
  pages still saying no deployment existed.
- **The gate and the walks catch different things.** The walks
  caught defects the tests had not: the Origin check on an IP address and tests consuming the
  development database's sequence (steps 1 and 2); in step 5, a Copilot turn that could not finish
  after an empty model reply, and a stale clock on the activity list; in step 7, a forecast that
  its own past tests showed ran high. That is evidence for walking, and also a reminder that walks
  are not exhaustive.
- **One machine, one day.** Timings and behaviour were measured on one development machine. CI
  first ran on 2026-09-20, when the repository was published, and failed twice on faults no local
  run could show: a settings test that read the environment the workflow sets, and an action
  looking for a file at the repository root. Both were fixed the same day.
- **Known shortcuts** are listed, each with its fix, in `../99-pending.md` under `demo-debt` (D-17).
