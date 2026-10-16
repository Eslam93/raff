---
title: How the system is built - components, data model, request flows, security controls and tests
status: verified
as_of: 2026-10-16
last_verified: 2026-10-16
verification_method: Updated after step 7 and again on 2026-09-20 after the deployment, from the code as published, the builders' reports, the full gate (verify.sh --full, 23/23 with REQUIRE_DB=1) and browser walks of every step's checklist against the Docker stack, including live Copilot turns
scope: The application in repo/ as of step 7 (core, sign-in and roles, operations, the Copilot with its member, staff and analyst faces, confirmed Borrow and Return, typed metric queries and forecasts, ISBN lookup and covers, catalog filters). Exploratory questions (A-X06) are designed, not built
confidence: High for structure and flows, each read from code or exercised in a browser walk. Medium for performance claims, measured once on one machine
known_gaps: No load test. Google sign-in is covered by tests against a fake identity provider and was exercised against Google on 2026-09-19 and 2026-09-20. The Copilot has been run live with one model only. The deployment of 2026-09-20 (operations.md) has had no users but its owner, so nothing here is measured under real traffic
supersedes: the 2026-09-20 version, which predates holds and renewals (E19, E20)
reverify_when: A step changes a layer, a table, a security control or the Copilot loop
---

# System overview

## Shape

One container serves everything from one origin: FastAPI serves the API under `/api` and the built
React app for every other path (`repo:repo/backend/app/frontend.py`), so cookies need no
cross-site settings and there is no CORS. PostgreSQL holds all state. The image is built by
`repo:repo/Dockerfile`; `repo:repo/docker-compose.yml` runs Postgres, a one-shot migration and the
app. Verified 2026-09-19 by `docker compose up --build` and browser walks.

## Backend layers (`repo/backend/app`)

| Layer | Where | Rule |
|---|---|---|
| Routers | `repo:repo/backend/app/api/routers` | thin: parse, check permission, call a service, shape the response |
| Permissions | `repo:repo/backend/app/api/deps.py` | `current_user` (401) and `require_staff` (403) dependencies on every route |
| Services | `repo:repo/backend/app/services` | every business rule: catalog, members, circulation, dashboard, activity, auth |
| Models and migrations | `repo:repo/backend/app/models`, `repo:repo/backend/alembic/versions` | SQLAlchemy 2 async; hand-reviewed migrations 0001 to 0005 |
| Copilot | `repo:repo/backend/app/copilot` | the AI module; it calls the same services with the signed-in user |
| Cross-cutting | `repo:repo/backend/app/middleware`, `repo:repo/backend/app/core` | request id, security headers, access log, origin check, error envelope, settings |

Every error leaves as one envelope: `{"error": {"code", "message", "details"}, "meta":
{"request_id"}}`; validation errors list `{"location", "message", "type"}` without echoing input.

## Data model

| Table | Holds | Notable constraints |
|---|---|---|
| `books` | titles | ISBN unique among non-archived books; trigram indexes on title and author (D-18) |
| `copies` | physical copies | `CP-0001` codes from a sequence |
| `members` | borrowers | unique lower(email); trigram index on name |
| `loans` | a copy lent to a member | one active loan per copy: partial unique index where `returned_at` is null (D-12) |
| `activity_events` | append-only record | actor name and user id, `via` ui, copilot or system |
| `users`, `sessions` | sign-in | sessions store only a SHA-256 of the cookie token |
| `copilot_conversations`, `copilot_messages` | Copilot memory | a conversation belongs to one user and one face |
| `copilot_proposals` | Borrow and Return the Copilot prepared | bound to the user who asked; pending for 10 minutes; confirmed, cancelled, failed or expired once |
| `holds` | a member in line for a book, then a copy set aside for them (since 2026-10-16) | one open hold per member and book; one ready hold per copy (partial unique indexes); place in line derived |
| `renewals` | each renewal of a loan: previous and new due time | a loan's renewal count is its number of rows |

Availability and overdue are derived in queries, never stored. Since 2026-10-16 one expression
decides whether a copy is on the shelf (`repo:repo/backend/app/services/availability.py`): in the
catalog, not on loan, and not set aside by a ready hold whose pick-up time is still ahead. Deleting a book with loan history
archives it instead (E15).

## Request flows

**Borrow.** `POST /api/loans` → `circulation` service checks the copy and member, inserts the loan
and one activity event in one transaction. Two simultaneous borrows of one copy: the unique index
rejects the second and the service turns it into 409 `copy_unavailable`. Verified by an
integration test that races two real connections (`repo:repo/backend/tests/integration/test_concurrency.py`).

**Holds.** Every change to a book's copies or line (borrow, return, add copies, place, cancel)
first settles the book's holds in its own transaction, under a per-book advisory lock taken before
any row lock: ready holds past their pick-up time expire, then each free copy is set aside for the
oldest waiting hold. A loop in the app's lifespan settles any book that needs it once a minute
(`HOLD_SWEEP_SECONDS`), so expiry needs no job from the host. A copy set aside can be lent only to
its member (409 `copy_held`), and borrowing it fulfils the hold (D-27). Verified by integration
tests on PostgreSQL, including races of two real connections
(`repo:repo/backend/tests/integration/test_holds_concurrency.py`), and a browser walk on
2026-10-16.

**Renew.** One conditional update on the loan id, unreturned, and the due time that was read, so a
double submit counts once (409 `loan_changed`), then a `renewals` row. Refused at the renewal
limit, while someone waits for the book, and when the loan is already due at the 90-day limit.

**Sign-in.** Demo sign-in (`POST /api/auth/demo`) or Google (`/api/auth/google/login` and
`/callback`, OpenID Connect with PKCE through authlib). Either way the server creates a random
token, stores its hash, and sets an HttpOnly, SameSite=Lax cookie; sessions expire after 12 idle
hours or 7 days. State-changing requests whose Origin is neither the server's own origin nor listed
in `ALLOWED_ORIGINS` get 403 (`repo:repo/backend/app/middleware/origin_check.py`).

**A Copilot turn.** `POST /api/copilot/chat` streams server-sent events. The face comes from the
role (`repo:repo/backend/app/copilot/faces.py`): two faces in code, member and staff, with the
analyst's tools carried inside the staff face, which is what "three faces in one panel" means in
the product's words (D-06); the model (OpenRouter, D-11, D-19) may call only
that face's tools (`repo:repo/backend/app/copilot/tools.py`), whose parameters reject unknown fields
and never carry an identity. Up to 6 tool rounds inside one 45-second deadline; the reply must pass
the number check (`repo:repo/backend/app/copilot/numbers.py`): every digit run must appear in the
lookup results or the user's words, else one corrective retry, then a plain rendering of the
results. An empty reply gets one nudge with the tools still offered, because the model sometimes
stops between the steps of a task. Measured live 2026-09-19: about 4 to 9 seconds per turn with
google/gemini-3.8-flash.

**A Borrow or Return through the Copilot (D-07).** The staff face's `prepare_borrow` and
`prepare_return` tools check everything the change will check, then store a proposal
(`repo:repo/backend/app/copilot/proposals.py`) and show it as a card; they never write a loan. The
user's Confirm calls `POST /api/copilot/proposals/{id}/confirm`, which locks the proposal's row,
refuses one that is no longer pending or has expired, and runs the same circulation service as the
web app with `via="copilot"` and the user as actor, so the loan, its activity event and the
proposal's new status commit together. When the service refuses (for example, the copy was lent at
the desk in the meantime), nothing is kept and the proposal is marked failed with the reason. A
note in the conversation tells the model the outcome, so a follow-up question gets it right.

**An analyst question (D-08, D-20).** Staff questions about how the library is used go through two
tools, `describe_metrics` and `query_metrics` (`repo:repo/backend/app/copilot/analyst.py`). The
model fills a typed query (metric, grouping, filters, period, comparison, sort, limit) whose every
level rejects unknown fields; the metric service (`repo:repo/backend/app/services/metrics`) checks it
against the catalogue, resolves the period against today in UTC, and runs fixed, parameterised SQL
chosen from a map of column expressions, so nothing the model writes becomes SQL text. The service
computes totals over the whole selection (never a sum of rows), shares, and changes against the
comparison period, rounded to one decimal, so every figure a reply may quote is in the result. The
panel shows the result as a table, with a bar or line chart when the server asks for one; the chart
code loads only then. Measured 2026-09-19 on the demo data: every metric query runs in under 6 ms
warm and 20 ms cold, so no index was added.

**A forecast (D-09).** `forecast_metric` forecasts monthly loans, returns or new members one to
six months ahead (`repo:repo/backend/app/services/metrics/forecast.py`), with no statistics
library: each month is the same month a year earlier times the trend of the last 12 months
against the 12 before. The method is then run from every past month with two years before it, and
its misses against what happened set both the likely range (the 10th to 90th percentile of the
misses, so about eight months in ten fell inside) and a correction of the forecast itself (the
median miss). It refuses, saying what it has and what it would need, when the history is too
short, a month averages under ten, or the typical miss is over 35%, and gives the trend instead.

**ISBN lookup and covers (D-13).** `GET /api/isbn/{isbn}` (staff) asks Open Library's search for
title, author and first publication year, with a 6-second timeout and a 24-hour in-memory cache;
the add-book form fills itself from the answer and works without it. Browsers load covers from
Open Library's cover host, which redirects to the Internet Archive; the Content-Security-Policy
allows exactly those hosts for images. The demo catalog's ISBNs were checked against Open Library
by `python -m app.seed.isbn_check` (`repo:repo/backend/app/seed/isbn_check.py`): all 267 matched
their books, and 17 of the 19 titles without one gained one.

## Security controls (what exists, as of step 7)

- Server-side authorization on every endpoint; a permission-matrix test covers every endpoint for
  anonymous, member and staff users (`repo:repo/backend/tests/integration/test_permissions.py`).
- Members never receive borrower identities; their loan endpoint takes no member id.
- Sessions: hashed tokens, idle and absolute expiry, server-side revocation, Secure cookies in
  production; production refuses to start with a weak `SESSION_SECRET`.
- No passwords exist in the system: a named user signs in with Google, and the demo buttons open a
  session on one of two shared accounts that hold no personal data (D-05). Those buttons are a
  setting, off by default in production, and the session they create follows the same rules as any
  other. The first demonstration deployment turned them on deliberately, so anyone who opened it
  could act as staff and change the generated library (`operations.md`, history since 2026-10-16).
- Origin check on state-changing requests; strict Content-Security-Policy and security headers.
  Images may come only from the app and Open Library's cover hosts; on the product's own pages no
  script, style or data request goes to another host, and the ISBN lookup runs on the server. The
  interactive API documentation is the one exception, because it loads its viewer from a public
  content delivery network, and it is served only outside production.
- The Copilot changes nothing by itself: Borrow and Return are server-stored proposals, bound to
  the user who asked, confirmable once within 10 minutes, and only through staff-only endpoints
  (D-07). Another user's proposal reads as not found.
- The analyst is read-only and staff-only; the model never writes SQL (D-08).
- Known gaps are listed as `demo-debt` in `../99-pending.md` (D-17).

## Frontend (`repo/frontend/src`)

React 19 with TanStack Query, react-router and shadcn-style components on Tailwind 4, with light
and dark themes. One feature folder per area (`repo:repo/frontend/src/features`): books, members,
loans, circulation, dashboard, activity, auth, copilot. One API client reads the error envelope;
a 401 anywhere returns to sign-in once. The Copilot panel reads the event stream and renders
results with the same components the pages use. Two pages are readable without signing in, the
privacy notice and the terms (D-24). Every page after sign-in loads from its own file,
and the chart library only when a chart is shown: measured 2026-09-19, the first load is 526 kB
(167 kB compressed) against 718 kB before the split.

## Demo data

`python -m app.seed` generates a library from seven reader personas (D-10): 286 real titles, about
490 copies, 200 members and about 5,500 loans over three years ending today, in about 2 seconds,
deterministic for a seed and a date (`repo:repo/backend/app/seed`). Titles and members are fixed;
copies and loans depend on the day it runs, because the three years end on that day. Measured
inside the Docker image: 484 copies and 5,482 loans on 2026-09-19, 489 and 5,420 on 2026-09-20.

## Tests and the gate

`bash .claude/tools/verify.sh --full` runs the harness checks and `.claude/tools/verify.project.sh`:
ruff, formatting, mypy strict and pytest for the backend (780 tests collected on 2026-09-20;
integration tests use their own `library_test` database and fail instead of skipping under
`REQUIRE_DB=1`), and lint, typecheck, Vitest and the build for the frontend (239 tests on
2026-09-20). The Copilot is tested with a scripted fake model; the fake cannot be enabled in
production. CI (`.github/workflows/ci.yml`) runs both halves of the gate, backend and frontend checks and the
harness checks, plus a Docker build. The harness checks were run on Linux in a container on
2026-09-20 and passed 20 of 20, the two Windows-only ones skipping themselves. CI ran for the
first time on 2026-09-20, when the repository was published, and passed on that commit, tagged
`v0.1.0` on 2026-10-16.
