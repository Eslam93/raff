---
title: Designed, not built - Raff's roadmap, the ideas left out of v0.1.0, and how each one would be built
status: draft
as_of: 2026-10-16
last_verified: 2026-10-16
verification_method: Designed on 2026-09-20 against the code as it stood at the end of step 7 and read on 2026-09-19, by four parallel design passes, one review pass and one audit pass that checked the claims about the current system against the code in repo/. Nothing in this page has been built or run
scope: What was deliberately left out: exploratory questions answered by model-written SQL (A-X06), the features listed as later in the product spec, further uses of AI inside this product, and what production would need. Each with its design, its risks and an effort estimate
confidence: High on what exists today, read from the code. Medium on the designs, which are reasoned and unbuilt. Low to medium on the effort estimates, which come from how long comparable steps took in this build
known_gaps: No idea here was prototyped, so no design is validated by running code. Costs and latencies for the AI ideas are not measured. External services named here were not evaluated beyond the ISBN lookup already in use
supersedes: the 2026-09-20 framing of this page as the record of what one submission left out; on 2026-10-16 it became Raff's roadmap (D-26)
reverify_when: One of these ideas is built, or a decision in decisions.md changes what the product may do
---

# Designed, not built

Raff's first complete version, `v0.1.0`, was built in one day with a deliberately small scope.
Plenty was left out on purpose. This page is the record of that thinking and, since 2026-10-16,
Raff's roadmap (D-26): for each idea, what it would do, how it would fit the system that exists,
what makes it safe or correct, what it would cost, and why it is not built yet.

## The roadmap

Decided with the owner on 2026-10-16, for small community libraries. Each item gets its own brief
before it is built.

| Order | What | Design |
|---|---|---|
| 1 | Holds and renewals | L01 and L02 below |
| 2 | Scan at the desk: a camera reads an ISBN or a copy's label, and staff print a QR label per copy | outline below; the full design comes with its brief |
| 3 | Import books and members from a spreadsheet | L07 below |
| then | An Arabic interface | not designed yet |

**Scan at the desk, the outline.** Copy codes (`CP-0001`) already identify every copy, and the
circulation desk already works by copy code, so a label only has to carry that code. A print page
lays out one QR code per copy for a book or a shelf, and the circulation desk and the add-book form
gain a "Scan" button that reads a QR code or an ISBN barcode through the device camera and fills
the field it belongs to. Reading barcodes in every browser needs a small new frontend library,
which is a stop for the owner. Status: PLANNED, nothing designed beyond this paragraph.

Nothing on this page is built. Everything about the current system was read from the code as it
stood at the end of step 7, on 2026-09-19, and is marked where it matters. The product rules that constrain every idea are in
`decisions.md`: the Copilot acts only through the same services and permission checks as the web
app, a person confirms every change, and every number in a reply comes from a lookup (D-07).

## Exploratory questions: letting the model write SQL safely

This is A-X06, planned as step 8 and not built: the owner decided against it on 2026-09-19. It would let staff ask the analyst a question the typed metric catalogue cannot answer, for example "Which categories have the most copies that nobody borrowed in the last twelve months?", which the catalogue cannot answer exactly because it counts titles never borrowed, not idle copies. The model drafts one SELECT statement, and the server decides whether that statement may run. Four parts keep the path safe, and none depends on the model behaving well: a gate that parses the statement and accepts only what an allowlist names, a database login role that can read only the allowlisted columns, a read-only transaction with a 3-second limit, and the number check the Copilot already applies to every reply. No part can prove that the query measures what the question asked, so the answer appears in the Copilot panel under an "Exploratory" label, for staff only and only when a setting turns it on. Status: SPECIFIED, not BUILT; nothing here has run, and the claims about current code were read from the code on 2026-09-19.

### When is it used instead of the typed path?

Only after the typed path was tried, and three things enforce that order. The staff prompt gains one rule: use the exploratory tool only when the catalogue description shows that no metric fits, and say so. A mechanical check refuses with `catalogue_not_checked` unless a catalogue description is already in the conversation. The evaluation counts SQL used for a question the catalogue answers as a routing failure.

### How does it fit what exists?

It adds one tool (`explore_data`, staff face only, behind a setting), one service module beside the metric service, one database login role, migration 0006 with its grants and the `copilot_explorations` table, a staff endpoint that returns one exploration, and one panel display kind. The turn loop, the tool framework and the number check do not change: every gate refusal is an ordinary application error the model reads. The service refuses a non-staff user itself, which is what D-07 requires. Before parsing, four checks run: the feature is on, a catalogue description is in the conversation, the staff member's own latest message is not SQL, and this turn has run fewer than three explorations.

### Which parser should the gate use?

Recommended: pglast, with the rule that only the rebuilt statement runs. pglast binds libpg_query, PostgreSQL's own parser as a C library, so the gate walks the tree PostgreSQL would build and prints a checked tree back to SQL. The main way past a SQL gate is text that the gate's parser and the database read differently, and PostgreSQL's block comments nest, so a parser that ends a comment at the first closing marker reads different code. The cost is a compiled extension whose parser version should match the server major version, and whose Windows wheels were not checked on 2026-09-19, while this project is developed on Windows. The fallback is sqlglot, pure Python and lenient by design, acceptable only under the same rebuild rule. Either library is a new backend dependency, which the project rules make a stop for the owner.

### What does the gate accept?

Exactly one statement, and a SELECT. Refused: every other statement type, from INSERT to `SET`, `DO`, `CALL` and `COPY`; a CTE holding INSERT, UPDATE, DELETE or MERGE, because PostgreSQL runs a data-changing CTE inside a SELECT; `WITH RECURSIVE`, which can loop to the timeout; `SELECT ... INTO`, which creates a table; locking clauses; parameter placeholders; a star in the output, while `count(*)` is allowed; more than twelve output columns or more than four levels of subquery. Allowed: `UNION`, joins, subqueries, `GROUP BY`, `HAVING`, `ORDER BY`, `CASE`, `FILTER` and window functions, with every subquery checked the same way.

Four tables in the `public` schema can be read: `books` without `description`, `copies`, `loans`, and `members` with only `id`, `joined_on` and `archived_at`. A description is long free text and the most likely place for hidden instructions. Out of reach entirely: `users`, `sessions`, the Copilot tables, `activity_events`, `alembic_version`, `pg_catalog` and `information_schema`. A column counts as read when it appears in `WHERE` or `GROUP BY`, not only in the output, because filtering on an address pattern and counting rows reads the column a letter at a time. Names and addresses stay out because result rows go to the model provider (OpenRouter, D-11): the typed lookups send at most ten members with addresses, while a free query could send two hundred, so exploratory answers are aggregate only.

Functions are allowed by name: the aggregates, the ranking and offset window functions, the common string and date functions, and the comparison and arithmetic operators. Everything else is refused, and four refusals carry the weight: `pg_sleep` holds a connection; `pg_read_file` and `lo_import` reach the server's files; `set_config` and `current_setting` can turn off the statement timeout, which PostgreSQL cannot forbid a role to change; `query_to_xml` and its relatives run SQL passed as a string, which the parser sees only as a string. Casts are allowed to nine types, so a cast to `regclass`, which reads the system catalogue, is refused.

Every top-level output column must read an allowlisted column or be `count(*)`, so a constant output is refused, text constants included, because text holds digits. An output name containing a digit is refused too, because output names return to the model as column names and the number check reads them. The gate sets a limit of 201 rows and the runner keeps 200.

### Where does the statement run?

Under a separate login, `library_explore`, through its own pool of two connections. An operator script creates the role once, because that needs a privileged database user a managed plan may not give. The role carries a connection limit of 2, read-only transactions by default, a 3-second statement timeout, UTC and a search path of `public` only. Column grants, not table grants: PostgreSQL checks privileges per column, so the database refuses a member address even if the gate lets it through. A separate login rather than `SET ROLE`, because after `SET ROLE` the session user is still the application role, so a statement reaching `RESET ROLE` gets full rights back. The runner sets the statement timeout again inside the transaction in case the role default was changed, fetches at most 201 rows, and rolls back, while a 4-second application timeout cancels a query the database timeout missed. Where a managed plan cannot provide a second role the feature stays off, because a mode relying on the gate alone would turn a gate bug into a data leak.

### What does the answer look like, and what is recorded?

The model reads the column names, the first 50 rows, the row count, whether rows were cut, and the columns read per table; the SQL text never returns to the model. The panel gets a display kind of its own: an "Exploratory" badge with one sentence of warning, the table, the tables and columns read, and a "Show the query" button that fetches the rebuilt statement. Every call writes one row to `copilot_explorations`, including refusals and timeouts, and the exploratory role cannot read that table. That query button changes a product rule: spec section 3.4 and D-08 say users never see or provide SQL, and the recommended new wording is that users never provide SQL while staff may open the statement behind an exploratory answer. That is the owner's decision, recorded before any build.

### What could go wrong?

A writing, locking or creating statement meets three barriers: the gate, the read-only transaction and the role's lack of write privilege. Private data meets the column allowlist and the column grants, so a resolver bug surfaces as a database error rather than a leak. Invented numbers meet the number check, the hidden SQL text and the constant-output rule, but arithmetic remains a gap, because multiplying a real count by zero and adding a made-up figure reads a real column. The number check proves a figure came from the database; it cannot prove the query measured what the reply says, which is why the path is labelled and never the default.

Text stored in a book description can try to instruct the model, and staff can read descriptions in the same conversation. The design does not detect such text, it makes following it harmless: an injected member address is refused as `column_not_allowed`, SQL hidden in a string is refused as `function_not_allowed` and would run as a role with no grant anyway, and three explorations per turn stop an injected loop. The reply goes only to the staff member who asked, who can already see those records, and the renderer draws no links or images.

### How would we know it works?

Deterministic tests decide correctness and run in the full verification, while a live-model evaluation decides usefulness, costs money and varies between runs, so it is run by hand, recorded with a date, and never counts as a passing check. Refusal tests cover at least one case per code, several of them a family: every statement type, each out-of-reach table, each refused function, and a member address reached through an alias or a CTE. Database tests connect as the exploratory role without the gate and check that the database refuses on its own: reads of member addresses fail for lack of privileges, an UPDATE fails in a read-only transaction, a triple self cross-join is cancelled after 3 seconds, and the role's column privileges match the allowlist module column for column. The live evaluation runs three sets three times each: about 15 questions the catalogue answers, compared with the typed path; about 15 outside it with hand-written reference SQL; and about 10 adversarial prompts, which must pass 10 of 10 every run.

### How much work is it, and why was it left out?

About 10 to 13.5 hours from agreement to commit, four to five times the staff face with confirmed Borrow and Return, mostly because it is a security control whose correctness rests on many tests: the gate and its tests are 4 to 5.5 hours of that, and the evaluation 2 to 2.5. Unusual cases in the resolver, pglast on Windows and a hosting plan that allows no second role could each add an hour or two.

In v0.1.0 the risk is higher than the value. The typed catalogue already answers every analyst story in the spec, each walked in a browser against the demo data, and nothing yet shows it is missing anything, while a demo has no real staff to ask. This would be the only part of the Copilot whose answers cannot be tested exactly, and its costs reach beyond its own code: a new dependency, a second database role on a hosting plan not yet chosen, and a change to a product rule, which makes it Tier 3 and starts it with a decision entry. It would also end the simplest safety statement the Copilot can make today, that the model never writes SQL (D-08).

## The features left for later

The spec's "Later, not now" list holds fourteen extensions, L01 to L15 without L11, which became the analyst forecast (D-09). Each is designed against the code as it stood on 2026-09-19, and nothing is built or tested, so these designs are reasoned from the code, not demonstrated. Estimates are calibrated against this build, where the staff face with confirmed Borrow and Return took 2 to 3 hours. The items below add up to about 48 to 69 hours of build, and about 54 to 77 with the extras each one names, ordered so that items needing no outside decision come first.

### What do all of these designs build on?

- The circulation service holds every lending rule, and `check_borrow` decides a borrow without writing, so a rule added there covers the desk and the Copilot at once.
- Races are settled by the database: the partial unique index on active loans (D-12) and the conditional update on an unreturned loan. Every new write below reuses one of the two.
- A proposal is the only path for a Copilot write (D-07), and it is staff only today. A member hold or renewal needs the action list, the endpoints and the card to change together, an authorization change costing a decision entry, a spec change and 1.5 to 2 hours, counted once.
- There is no scheduler, so hold promotion and reminders need a job command started hourly by a hosting platform that is not chosen, and the due day is a UTC day, so a library time zone setting comes before reminders or fines.

### L01, holds

A `holds` table with two partial unique indexes, one open hold per member and book and one ready hold per copy, where place in line is derived. On return the oldest waiting hold is taken with `FOR UPDATE SKIP LOCKED` inside the return transaction, and a ready hold is live only while its pickup time is later than the database clock, so an unclaimed hold releases its copy with no write. The real risk is that availability is written out separately in at least six places across three services, so the first task is one shared free-copy expression. 5 to 7 hours, plus the member proposal change and 1 hour for the promotion job. Left out because section 6 rules out reservations.

### L02, renewals

A renew function beside borrow and return. The due date column keeps the current due date, so overdue, due soon and every metric keep working, while a renewals table keeps the previous and new due dates. One conditional update on the loan id, the unreturned state and the due date seen, so two renewals cannot both count. 2 to 3 hours, plus 1 hour for the Copilot tool. Left out because every rule, from the renewal limit to the treatment of a waiting hold, is a lending-policy choice the owner has not made.

### L04, fines

A ledger, not a payment system. Account entries hold a kind, an amount as a whole number of the smallest currency unit and the rule used; rows are only inserted and the balance is a sum. A fine is derived at read time from the existing days-overdue expression and becomes a row at return, carrying its rule, so a later rate change never rewrites an old fine. `check_borrow` gains a blocked-member rule above a balance limit, and Copilot access stays read only. 4 to 6 hours. Left out because the rate, cap, grace days and blocking limit are policy nobody has decided.

### L05, lost and damaged copies

Copies gain a withdrawal reason (lost, damaged, withdrawn) set with the archive field, which already means out of circulation everywhere, and loans gain a closed-as value. A lost loan gets a return time, so it frees the one-active-loan index, and the metrics that read that field gain a closed-as filter, so a lost loan is never counted as a return. 3 to 4 hours. Left out because archiving the whole book already covers removing a book.

### L14, configurable lending policies

Today one setting holds the loan period, 14 days by default and 1 to 90 allowed. A `lending_policies` table keyed on optional category and member group, with a unique index over active rows so two rules never match equally, and the loan stores its policy, so an edit applies to new loans only. The active-loan limit then needs an exclusive lock on the member row, because today a borrow locks the book row with a shared lock, which does not make two borrows for one member wait for each other. 5 to 7 hours. Left out because it turns a simple product into an admin platform.

### L03, email reminders

Seven moving parts, of which only the recipient queries exist: the hourly job, a `notifications` table with a unique dedupe key and a delivery status, a transactional provider needing an API key and a sending domain with SPF, DKIM and DMARC, a signed webhook that can change only a status, unsubscribe through an opt-out column, and a system activity event. The job inserts with `ON CONFLICT DO NOTHING` and claims rows with `FOR UPDATE SKIP LOCKED`, so overlapping runs never send twice, and templates are fixed text, so no model writes a message that reaches a member. 4 to 6 hours against a fake provider. Left out because there is no scheduler, provider account, sending domain or hosting target, and section 6 rules out messaging.

### L06, several branches

A `branches` table, a home and a current branch on copies, a branch and a returning branch on loans, and a `transfers` table where a copy in transit is available nowhere; the staff working branch comes from the session, never from the model. 10 to 14 hours, the largest item here, though the migration creates one branch and assigns everything to it, so nothing changes until a second branch exists. Left out by D-01 and section 6 of the spec: Raff serves one library.

### L07, bulk imports

Staff upload a CSV of books or members, see every row checked, then confirm. Each row goes through the existing create functions, so validation, the unique indexes and the activity events are the same, and the stored import is confirmable once by its uploader on the proposal pattern, under limits on file size and row count. 3 to 5 hours. Left out of v0.1.0 because the demo library comes from the seed; a real library needs it on its first day, so it is third on the roadmap.

### L13, shelves and locations

Books gain a call number and copies gain a location, both shown in the book form, the copies table and the Copilot book lookup; free text first, because a locations table earns its place only when staff need to filter or count by location. 1.5 to 2 hours for the shelf mark, 3 to 4 hours more for the inventory check that lists the copies a shelf scan expected but did not see. Left out because v0.1.0 did not need to know where a copy stands.

### L15, more staff roles

Roles stay a fixed list in code, mapped to permissions (`catalog.write`, `circulation.write`, `members.write`, `analytics.read`, `policies.write`), and the staff check becomes a check for one permission. The staff face is built from the same map, and the confirm endpoint checks the action's permission again. 3 to 5 hours. Left out by D-02: two roles that are really exercised beat a matrix nobody uses.

### L08, L09, L10 and L12, the AI items

- **L08, custom reports.** A saved report is the typed query the analyst's model already fills, stored by name and run again with a relative period, so there is no new query path and D-08 holds. 2 to 3 hours. Left out because the analyst answers the same questions on demand.
- **L09, recommendations.** Titles borrowed by the same members, ranked against what their popularity predicts. 5 to 7 hours. Left out because section 6 rules it out and seeded data repeats the generator's personas.
- **L10, metadata enrichment.** Not planned: the ISBN lookup (D-13) fills title, author and year, and a model would add guesses where a record exists.
- **L12, AI bulk actions.** One proposal holding many actions, each rechecked at confirm. Not estimated, and left out because one confirm over many records weakens the D-07 rule that the user confirms the exact action.

## More AI, under the same rules

Seven more uses of the Copilot were designed against the module as built and deliberately not built. Each keeps the rules already in force (D-07): the capability exists in the service layer first, the identity comes from the session and never from the model, a change happens only when the user confirms a server-stored one-time proposal, and every number comes from a lookup and passes the number check. Recommended first: the evaluation harness, because every other idea changes a prompt, a tool or a model, and today each change is judged by a few questions typed by hand. Figures below were measured on 2026-09-19 against the local Docker stack, which holds 286 titles and 5,482 loans.

### 1. Recommendations that show their reasons

A recommendations service reads only loans, copies and books, feeding a book page row and one member tool that takes no member parameter. A title pair counts only at a support of 5 distinct members and a lift of 1.5, so no suggestion rests on one other person's reading, and members with fewer than 3 loans see "Popular now", never "For you". 5 to 7 hours. Left out because L09 defers recommendations, and the demo data cannot show the design is honest: 26,901 of the 40,755 pairs co-occur and every pattern repeats the generator's personas (D-10).

### 2. Catalog quality: the Copilot flags, staff decide

A fixed-rule service, not the model, finds probable duplicates, missing ISBNs or years, and ISBNs whose Open Library record names a different title or author. A `catalog_flags` table stores each problem with its status and who dismissed it, and fixes go through the existing book update as a new proposal action. The model never supplies a value from its own knowledge (L10): the server fetches the Open Library value, or the value must appear word for word in the staff member's own messages. 6 to 8 hours. Left out because the demo catalog has nothing to find, all 267 original ISBNs matched, and widening AI writes needs an owner decision.

### 3. Search in plain words, with the search it ran shown

Plain-language discovery is built (A-M01). Missing: the four sort orders the service already supports, a line showing what was actually searched, and a statement of what the catalog cannot search. The catalog tool gains a sort field and a server-built description of the search it ran, shown as one line beside an "Open in Catalog" link carrying the same query, category and sort. The line comes from what the server ran, so the search cannot be misreported. 1 to 2 hours. Left out because the useful core is built, and the requests it would most help cannot be answered anyway: category is the only age signal, and none of the 286 books has a description or a subject field.

### 4. A morning briefing for staff, built only from lookups

"What needs attention today?" returns the counts, loans that became overdue since yesterday, loans overdue by more than 30 days, and flags. The dashboard service already computes the counts and lists; new are a briefing service, an "Unusual activity" list on the Dashboard, and one staff tool, with no schedule and no email. The number check confirms that a number appears in the lookup results, not that it carries the right label, so the labelled figures stay in the server-rendered card and the model writes two to four sentences above it. 3 to 5 hours. Left out because the dashboard already shows the counts and lists, and the flag rules need real use to tune.

### 5. Reminder drafts that staff review and send

Reminders must exist as a product feature first (L03). This idea adds a "Send reminder" button calling a send function, then one staff tool and a `send_reminder` proposal action on top. The facts come from a server template, and the model writes only a short free-text part that the number check covers; confirm sends exactly the stored text through the same function as the button. The service, not the prompt, allows only overdue or due-soon active loans, one reminder per loan within a set number of days, and no opted-out member. 6 to 9 hours. Left out because messaging is out of scope, and a draft with no way to send it is the AI-only workflow the scope rule refuses.

### 6. An evaluation harness for the Copilot, to build first

Scripted conversations run the real Copilot against a known library and score the lookups called, the refusals, whether the number check passed without a retry, and whether the expected facts appear. The engine already returns the outcome, tools, rounds, model calls and tokens, the fake model already plays a script, and the demo library is identical for a given seed and date. Scenarios are data files whose facts are computed at run time from a named service call, so no answer key is stored. Each scenario runs 3 times and the report gives rates, because on 2026-09-19 OpenRouter refused a call with a 400 twice in about 60 live turns and each question succeeded on repeat. Every live run saves its replies as a fake-model script that CI replays, though only a live run scores the model's judgement. 5 to 7 hours. Left out because the owner judged evaluation scaffolding not worth the time for demo data (D-10); that decision was about an answer key, which this harness does not need.

### 7. Cost and latency controls

The settings already cap a turn at 45 seconds, 6 tool rounds, 2,000 output tokens per call and 20 messages per user per minute, and the engine sends at most 20 messages of history (a constant in the conversations module, with no setting) and totals a turn's tokens and logs them, but nothing limits that total. Measured on 2026-09-19 from the JSON, not with the model's tokenizer: the staff face sends a 4,381-character prompt and 12,505 characters of tool definitions for 13 tools with every call, so its fixed part is about 4,000 tokens, sent at least twice in a turn with one lookup. A turn-token budget would end a turn with the plain rendering of its lookups, on the path the round limit already uses, so no answer is cut off mid-sentence. A model per face is the next step: the member face, with 4 tools and no writes, is the first candidate for a lighter model, about $0.20 and $1.20 per million tokens against $0.75 and $3.75 (D-19), and only when the harness scores the new one within an agreed margin. 3 to 5 hours. Left out because a typical turn costs well under a cent at demo volume.

## From demo to production

The application runs in demo posture (D-17): hardening the spec does not require is a `demo-debt` line and does not block a step. Claims about the code come from reading it on 2026-09-19, and nothing designed here has been built. Two things changed on 2026-09-20, after this section was written: the application was deployed, one instance behind a content delivery network (D-23 and `../20-architecture/operations.md`), and CI ran for the first time on the published repository and passed. Read the areas below against that: the host is chosen, CI exists, and there is something to observe.

### 1. What has to change before the app runs more than one worker?

Most shared state is already in PostgreSQL, but two things live in process memory: the Copilot rate limit, 20 messages per user per sliding minute, so N processes give a user N times 20, and the ISBN cache, 24 hours and at most 1,000 entries. Both move to tables, the rate limit decided by one upsert returning the count, which is a fixed window rather than a sliding one. A new liveness endpoint answers without touching the database, so a database outage does not restart every container. Recommended: PostgreSQL, not Redis, because the write load is small. About 3 to 4 hours. Left out because one process serves the demo.

### 2. What does the database need before it holds real data?

Today one role owns and uses every table, and no backups exist. Design: three roles, an owner for migrations, an application role with only SELECT and INSERT on activity events, and an analytics role reading books, copies, loans and the member id and join date only. Backups are managed snapshots plus a nightly dump to a separate account, with targets of at most 5 minutes of lost data and service back within 1 hour, and a monthly restore drill, because a backup that has never been restored proves nothing. About 7 to 8 hours. Left out because the data is generated.

### 3. Which security controls exist, and what would production add?

Built and tested: a session token stored only as its SHA-256 hash in an HttpOnly, SameSite=Lax cookie, expiring after 12 idle hours or 7 days; an Origin check on state-changing requests; a strict Content-Security-Policy with HSTS in production; and a permission matrix test that calls every endpoint as anonymous, member and staff. The gaps: no rate limit on sign-in, no way to disable a user, since the staff list decides a role only at first Google sign-in, and, until 2026-09-20, a CI file that had never run. Design: about 10 sign-in attempts per minute per client address on area 1's counter table, a disabled-at column refused at the next request, dependency and image scanning in CI, and the model key rotated every 90 days under a provider spending cap. About 5 hours. Left out because demo sign-in is one button per role, and because these are controls for real users, which this deployment does not have.

### 4. What changes before real member data is stored?

Today the activity record writes member names into its sentences, conversations never expire, and every turn sends the provider the last 20 messages and the lookup results. Minimisation first: new events keep ids only and the name is joined at read time, with a migration rewriting the old sentences, while staff names stay, because an audit record must show who acted. Retention in the daily job deletes conversations 30 days after their last message. Erasure is a staff action refused while a loan is active: the member row keeps its id and join date, the name becomes "Former member", the linked user row is deleted, and loans stay and point at the anonymised row. About 8 to 8.5 hours, legal review not included. Left out because the demo holds only generated people (D-10).

### 5. How would the team know the production app is healthy?

The app already writes one access line per request and one turn line carrying the face, outcome, tool rounds, model calls, tokens and latency, but nothing reads the logs. The first step needs no code, because the host's log service can count outcome shares, latency percentiles and model errors. Tracing with OpenTelemetry comes after, with spans that never hold message text, and it is a new dependency needing the owner's approval. Six starting alerts, from readiness failing for 2 minutes to any 401 or 402 from the provider. About 6 hours. Left out while nothing was deployed; since 2026-09-20 there is something to observe, and this is the first area a next step would take.

### 6. Why should due dates follow the library's time zone?

Every day boundary is UTC today, so at UTC-5 a loan becomes overdue at 19:00 local time, possibly while the library is open. Design: one setting holding an IANA name, checked at start and defaulting to UTC, and one module owning today, end of day and a SQL helper for the local date, replacing every UTC-date helper. The first start stores the zone and the app refuses to start when the setting differs, because a data migration must move every existing due date. About 4 to 5 hours, mostly in the metric service. Left out because the demo library has no local day to match.

### 7. How would covers stay under the Open Library limit?

Open Library allows 100 cover requests by ISBN per 5 minutes per address before answering 403, which staff paging through the catalog can pass in a few minutes. Requests by Open Library's own cover id do not count. Design: a nullable cover id on books, filled by the existing lookup and by a one-time backfill at one request per second, with the cover component trying the id address, then the ISBN address, then the placeholder. The risk is that the cover id belongs to the work, not the edition, so the image may show a different edition; that is strongly inferred and was not checked against the 284 demo ISBNs. About 2 to 3 hours. Left out because the placeholder is the designed fallback.

### 8. What would accessibility and right-to-left languages take?

Built along the way: a skip link, live regions, every chart paired with a captioned table, and dates and numbers through `Intl`. Not done: no automated check and no screen-reader walk has been run, there is no message catalog, and several dozen left and right utility classes across the web app do not flip. The number check compares runs of digits as text, and the pattern also matches Arabic-Indic digits, so a reply writing 37 in Arabic digits would be rejected and the turn would fall back to plain results; checked with a local Python interpreter, not through the app. Design: axe checks in the test suite and screen-reader walks first, then a message catalog, logical Tailwind classes and the number check converting digit runs to ASCII. About 5 to 6 hours for the accessibility audit, and 12 to 16 hours for the catalog and Arabic. Left out of v0.1.0, whose spec is English-only; an Arabic interface is on the roadmap after imports.

### What to do first, and why

Backups, the restore drill and migrations as a release job come first, because a lost database is the one failure no later step can repair. The library time zone comes next, before the first real loan, because after that every stored due date needs a data migration. Then security for real users, then alerts from the log lines that already exist, then privacy before the first real member record, then covers by cover id. More than one worker and tracing wait until traffic needs them: one process is expected to serve a single library, and that has not been load-tested. Areas 1 to 7 add up to about 35 to 40 hours, and area 8 to about 17 to 22 more.
