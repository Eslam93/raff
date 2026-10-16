# Knowledge base

The working record of this project: what the product is, how it was built step by step, what was
decided and why, and what is still open. A suggested reading order:

1. `10-product/product-spec.md`: what the product is and what it deliberately is not.
2. `30-delivery/build-log.md`: each step, what was verified, and what went wrong.
3. `20-architecture/system-overview.md`: how the system is built.
4. `decisions.md`: every decision, with the options and the reasons.
5. `40-method/how-this-was-built.md`: who decided what, and the guardrails.
6. `99-pending.md`: what is still open, including known shortcuts.
7. `50-designs/designed-not-built.md`: Raff's roadmap, and the ideas left out on purpose, each
   designed against this system, with its risks and what it would cost.
8. `20-architecture/hosting.md`: where the public demo runs since 2026-10-16, its limits, updates
   and backups.
9. `20-architecture/operations.md`: history: how the first live demonstration ran, until it was
   torn down on 2026-10-16.

**Two warnings, before anything else.**

1. **Everything here is point-in-time.** Every substantial page carries a header saying when the facts were gathered, how they were verified, and what was not checked.
2. **The absence of a subject here is not evidence about it.** Silence is a gap, not a clean bill of health.

## Where it lives, and why

This knowledge base is committed inside the repository, under `docs/knowledge-base/`, next to the
application in `repo/` and the AI working harness in `.claude/`. It ships with the code on purpose
(D-16): the product spec, the decision log and the open items are how the build was steered, and a
reader should be able to check the code against them.

## The rules for writing here

The path-scoped rule `.claude/rules/knowledge-base.md` loads whenever a file here is touched. Never a secret value. Describe the system, not the people. Keep negative results. Never assert a changeable condition in the present tense: write the measurement, dated, with its source.
