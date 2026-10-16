# Pending

Everything found and not acted on. One line each, same turn, grouped by who can act. `P0` blocks the current goal · `P1` matters soon · `P2` worth doing · `?` needs a decision. This is the index of what is open, not the evidence.

## 1 · Only the owner can answer these

- `P2` The live demo was torn down on 2026-10-16 (D-25), but the two `library` records for
  eslamhamed.com still sit at the registrar, pointing at a CloudFront address that no longer
  exists. Remove them in the registrar's DNS settings.
- `P2` The Raff demo has no uptime monitoring and no alert when its nightly backup fails, and no
  restore has been rehearsed (`20-architecture/hosting.md`).

## 2 · Needs a decision

- `?` Whether the next deployment probes liveness with `/api/health`: it returns 503 when the database is down, so as a liveness probe a database outage would restart the container. Use it for readiness only, or add a separate liveness endpoint.

## 3 · We can do this ourselves

- `P2` Holds and renewals have no Copilot proposals: the Copilot reads holds but cannot place,
  cancel or renew for anyone (D-28). Adding them means member proposals, which are staff-only
  today (D-07).
- `P2` A Copilot confirm of a borrow refused because the copy is set aside for another member
  answers `proposal_failed` with the reason, not `copy_held` as its own code like
  `copy_unavailable` (`repo/backend/app/copilot/proposals.py`).
- `P2` The web app writes the renewal limit and the loan period as constants
  (`repo/frontend/src/features/loans/renewal.ts`), so "renewed N of M" and the date the renew
  dialog promises are wrong if an operator changes `MAX_RENEWALS` or `LOAN_PERIOD_DAYS`; whether
  Renew is offered still comes from the API. Expose them on `/api/auth/config`.
- `P2` `can_renew` is true for a loan already due 90 days ahead, which the API then refuses with
  `renewal_not_needed`. Fold that rule into `can_renew`.
- `P2` Nobody is told when a copy is set aside for them: there is no email yet. Members see it in
  My loans and on the book's page. Comes with L03, email reminders.
- `P2` The demo seed creates no holds or renewals, so a fresh demo library shows empty holds lists
  until someone places one.
- `P2` `demo-debt` The holds sweep runs in every app process. With more than one process each
  would sweep; the advisory lock keeps it correct, but the work repeats.
- `P2` Searching the catalog through the Copilot asks for each listed book's line and the member's
  own hold separately (up to 20 small queries for 10 books). Batch them in one query.
- `?` The web app's sign-in page test failed once under a slow full run on 2026-10-16 and passed
  alone and in later runs. Watch it; quarantine if it repeats.
- `P1` The privacy notice and terms (`repo/frontend/src/pages/notices-page.tsx`) are written for a
  demonstration with generated data. A library that runs Raff for real people needs its own: make
  the operator, the contact and the data kept a setting or an editable page before the first real
  library goes live.
- `P2` `.claude/tools/baseline.sh` (task sealing) is not called by any skill in this project's loop (D-15). It stays: the test guard reads what it writes, and the hook self-tests exercise it. Remove it with those test cases only if the task-sealing idea is dropped.
- `P2` The README has no screenshots. A screenshot of the dashboard, the catalog with covers and the Copilot answering with a chart would help a reader who cannot run it; frames from the demo video would do.

- `P2` `demo-debt` The activity log is append-only by convention: the application only inserts, but the database role could update or delete. Revoke UPDATE and DELETE on `activity_events` from the application role once roles exist.
- `P2` Loans fall due at the end of the due day in UTC and the web app shows due dates in UTC. A library time zone setting would make "due today" match the library's own day.
- `P2` If a page's file fails to load (for example after a redeploy renames the files), the page says so, but "Try again" does not fetch the file again; only a browser reload does. Retry the import on "Try again".

- `P2` `demo-debt` The Copilot's rate limit (20 messages per user per minute) is kept in memory by each process, so it resets on restart and multiplies with workers. Move it to PostgreSQL or Redis before running more than one worker.
- `P2` `demo-debt` Confirming a Copilot borrow commits the loan, its activity event and the proposal's status together, then stores the new loan's id on the proposal in a second commit (the circulation service creates the loan and commits). If the process stopped between the two, the proposal would read as confirmed with no loan attached; the loan and the activity log would still be right. Fix by letting the service take a caller-owned transaction.
- `P1` The Copilot's occasional "could not answer" (about one model call in thirty) is OpenRouter
  splitting Gemini calls between two providers, Google Vertex and Google AI Studio, while the model's
  reasoning signatures from earlier calls are only valid at the provider that made them. A call
  routed to the other provider is refused with 400 "Corrupted thought signature." Verified
  2026-09-24 by replaying a failed live conversation: sent as the app sends it, 4 of 4 were served
  by Vertex and passed; pinned to AI Studio, 2 of 2 failed with that error; pinned to Vertex, 2 of 2
  passed; AI Studio with the reasoning removed, 2 of 2 passed. It fails mid-turn too (after a
  lookup) and on the first call of a later turn. Fix: send `"provider": {"only": ["google-vertex"]}`
  with each request (a setting, so another model can drop it), or exclude Google AI Studio for the
  whole account in OpenRouter's privacy settings. The owner applied the account exclusion on
  2026-09-24; verified the same day: 8 of 8 replays served by Vertex and passed, and a request
  pinned to AI Studio was refused with "All providers have been ignored". Still open: the fix
  lives in the owner's OpenRouter account, not in the code, so a deployment with another key
  brings the failures back, and with one provider left there is no fallback when Vertex is down.
- `P2` `demo-debt` The ISBN lookup's cache lives in the process's memory (24 hours, at most 1,000 answers): it is lost on restart and not shared between workers. Move it to PostgreSQL or Redis with the rate limit.
- `P2` Covers are requested by ISBN, which Open Library limits to 100 requests per 5 minutes per address; past that it answers 403 and the placeholders show. Requesting by Open Library's cover id (`/b/id/<id>-M.jpg`) avoids the limit: store the id with the book (the search answer carries it).
- `P2` Two demo titles (Onyx Storm, Diary of a Wimpy Kid: Hot Mess) have no ISBN: the check found no matching edition with a cover. They show the placeholder.
- `P2` The ISBN lookup fills the year with Open Library's first publication year of the work, which can differ from the edition's (The Catcher in the Rye comes back as 1945). The form asks the user to check the details before adding.
- `P2` The web tests build a jsdom for every file, which is more than half their time and enough
  memory that a worker died with exit code 134 on a busy laptop: once on 2026-09-19 and twice on
  2026-09-20, each time in a different file, with every test that ran passing. Capping the pool
  at four workers fixed it (`repo/frontend/vitest.config.ts`). The suggested cure is one jsdom
  per worker (`pool: 'vmThreads'` or `isolate: false`), which would also cut the minute the
  suite takes; it changes how tests are isolated, so it needs a run of its own to prove.
- `P2` Nothing records who a request came from: the access log carries method, path, status,
  duration and request id; uvicorn's own access log is off; the CDN's access logs are off. So a
  visitor who never signs in cannot be told apart from a crawler. Measured 2026-09-22 on the live
  demo: about 1,800 requests in two days, no sign-in after 2026-09-20 09:12 UTC, and a few page
  loads that stopped at the sign-in page whose source is unknowable. Turn on the CDN's access logs
  (client address, user agent, country) if visits need to be known.
- `P2` `demo-debt` An unhandled database error is logged with its full traceback, and the engine
  is created without `hide_parameters=True` (`repo/backend/app/db/session.py`), so by SQLAlchemy's
  documented behaviour the log line would carry the SQL statement and its bound values, which can
  be what a user typed. Copilot turns already strip this; other routes do not. Strongly inferred
  from the code on 2026-09-22, not reproduced. Fix: pass `hide_parameters=True`.
- `P2` Every GET outside `/api` that is not a built file answers 200 with the app's HTML shell,
  so vulnerability scanners probing `/.env`, `/.git/config` or `/.aws/config` get 200 and nothing
  else (checked on the live demo 2026-09-22: 830 bytes of `index.html`; a path traversal is
  refused). Harmless, but it keeps scanners coming back; answer 404 for dot-paths and file-like
  paths that do not exist.
- `P2` Archiving a book cannot be undone from the product: no route clears `archived_at`, no list
  shows archived books, and an archived book is reachable only from a loan row's title link or a
  saved address. Since Delete archives any book that ever had a loan, archiving the wrong book is a
  one-way action. Add an archived filter and a restore action, both staff only.
- `P2` Copies can be added to a book but never removed or marked lost or damaged, so a miskeyed
  count of copies can only be corrected by deleting or archiving the whole book.
- `P2` Member search gives the Copilot at most 10 members and 5 by default. With six members named Daniel it listed five and asked which one, without saying a sixth exists. The data carries the total ("matches"); have the staff prompt mention when there are more matches than shown.

## 4 · Worth doing when someone is in that code anyway

Nothing open here as of 2026-09-19.
