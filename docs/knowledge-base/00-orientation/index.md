---
title: Where every page is, and what each one settles
status: verified
as_of: 2026-09-20
last_verified: 2026-09-20
verification_method: Rows checked by hand against the files present on 2026-09-20
scope: This knowledge base only
confidence: High that the table matches the files present; the pages themselves carry their own confidence
known_gaps: No screen-by-screen UX page, and no page on the infrastructure itself beyond what `../20-architecture/operations.md` records
reverify_when: Every time a page is added, superseded, or removed
---

# Index

## Start with one of these

| If you are | Read |
|---|---|
| reviewing the project | `../30-delivery/build-log.md` (the story, step by step), then `../40-method/how-this-was-built.md` |
| new to the project | `../10-product/product-spec.md`, then `../20-architecture/system-overview.md`, then `../decisions.md` |
| about to change something | `../99-pending.md` and the decisions it touches |

## Every page, and what it settles

| Page | What it settles |
|---|---|
| `../README.md` | what this base is and why it ships with the code |
| `../10-product/product-spec.md` | what the product is, its features with acceptance lines, the Copilot, the delivery order, what is out of scope |
| `../20-architecture/system-overview.md` | how the system is built: layers, data model, request flows, security controls, tests |
| `../30-delivery/build-log.md` | each step: what was agreed, built and verified, and what went wrong and how it was fixed |
| `../40-method/how-this-was-built.md` | who decided what, the loop every step followed, the guardrails, where the method stops |
| `../decisions.md` | every decision in force, with the options, the reasons and when to revisit |
| `../20-architecture/hosting.md` | where the public demo runs since 2026-10-16: the box, its limits, updates and backups (D-29) |
| `../20-architecture/operations.md` | history: how the first live demonstration ran, until it was torn down on 2026-10-16 (D-25) |
| `../50-designs/designed-not-built.md` | Raff's roadmap, and the ideas left out on purpose, each designed against this system, with its risks and what it would cost |
| `../99-pending.md` | everything noticed and not yet acted on |

## What is empty, and deliberately

- `_investigations/` and `_readings/` were never needed, so they are not in the repository (git
  does not carry an empty folder). Nothing was measured or read outside the pages above. Faults
  found during the build are recorded where they happened, in `../30-delivery/build-log.md`, and
  what is still open is in `../99-pending.md`.
