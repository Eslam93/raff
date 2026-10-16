---
title: Every decision in force, what each superseded, and when to revisit it
status: verified
as_of: 2026-10-16
last_verified: 2026-10-16
verification_method: Recorded as each decision was agreed with the owner, on 2026-09-19 and 2026-09-20. D-01 to D-20 are exercised by built, tested code (step 5 exercised D-07's confirmed writes, step 6 D-08 and D-20, step 7 D-09 and D-13); D-21 to D-24 were carried out on 2026-09-20. D-25 and D-26 were carried out on 2026-10-16: the AWS teardown was checked resource by resource, and the rename and tag were checked on GitHub
scope: Decisions about this project: product boundary, architecture, AI behaviour, delivery and ways of working
confidence: High that these are the decisions in force, because each was agreed explicitly. Medium on the reasoning where it predicts cost for steps not yet built
known_gaps: Where Raff is hosted next is open: D-25 tore the demo down and the owner's machine is not chosen yet
reverify_when: Whenever a decision is made or superseded, and at each delivery step's hand-back
---

# Decisions

One entry per real fork, newest first. Fields: decision · options considered · why · decided by ·
reversible or not · revisit when · supersedes.

### D-26 · The project continues as Raff, a side project for small community libraries

- **Decision:** the library system becomes Raff (رف, "shelf"), the owner's own project, for small
  community libraries: school, mosque or church, office, coworking, neighbourhood. The repository
  is renamed `Eslam93/raff`, the first complete version is tagged `v0.1.0` (6e86f70), and history
  continues as normal commits through pull requests into `main`. The code is published under the
  MIT licence. The roadmap, in order: holds and renewals, scanning at the desk with printed copy
  labels, imports from a spreadsheet, then an Arabic interface
  (`50-designs/designed-not-built.md`).
- **Options:** for the audience, small community libraries or a personal home library (which would
  remove the two roles); for the licence, none, MIT, or a copyleft licence.
- **Why:** the project was built for a one-off review and now stands as the owner's product.
  Community libraries match the existing staff and member model exactly. MIT is the simplest licence
  that lets others reuse the code.
- **By:** owner, 2026-10-16 · **Reversible:** the name and licence yes; the published history no
- **Revisit when:** a real library uses Raff, which moves the data posture (D-17) towards production.
- **Supersedes:** D-22 (the single published commit), and the end-task framing of D-14: publishing
  happened, and the project continues past it

### D-25 · The AWS live demo is torn down; hosting moves to the owner's machine later

- **Decision:** every AWS resource of the live demo was deleted on 2026-10-16: the CloudFront
  distribution and its certificate, the instance with its disk and the demo database (no backup),
  the Elastic IP, the security group, the IAM role and profile, and the four encrypted parameters.
  Each was checked gone. Hosting on the owner's own machine is to be decided after the reshape.
- **Options:** keep paying for the demo; tear it down.
- **Why:** the review it served is over, and it cost about eight to ten dollars a month.
- **By:** owner, 2026-10-16 · **Reversible:** yes, by deploying again; the demo data was generated
  and can be generated again
- **Revisit when:** the owner's machine is chosen.
- **Supersedes:** D-23

### D-24 · Google sign-in is open to any account, and the deployment publishes its notices

- **Decision:** the Google consent screen is published, so any Google account can sign in to the
  live demo and becomes a Member; addresses on the staff list become Staff. Publishing requires a
  home page, a privacy policy and terms, so the application serves `/privacy` and `/terms` without
  a sign-in: what a Google sign-in stores, what the demo accounts are, the one cookie, what reaches
  OpenRouter and Open Library, and that the data is generated and reset.
- **Options:** keep the consent screen in testing and add each reviewer as a test user; publish it.
- **Why:** a reviewer should not have to ask for access, and the notices are what an honest
  deployment owes anyone who signs in. The scopes are name, address and account id only, which
  Google does not require verification for.
- **By:** owner, 2026-09-20 · **Reversible:** yes, back to testing in one click
- **Revisit when:** the demo is taken down, or the deployment stops being a demonstration.
- **Supersedes:** none

### D-23 · The live demo runs on one EC2 instance behind CloudFront, on the owner's domain

- **Decision:** one t3.micro instance in eu-central-1 runs the same Docker Compose stack a laptop
  runs, and CloudFront serves it at `https://library.eslamhamed.com` with an AWS certificate. The
  instance answers only CloudFront, has no SSH key, is managed through Systems Manager, and reads
  its secrets from encrypted parameters. The subdomain is a record at the owner's registrar.
- **Options:** reuse the owner's existing 1 GB box and serve the app under a path of their
  portfolio; a new instance with its own subdomain; a new instance with only the address AWS gives.
- **Why:** the subpath would have needed an application change and would have put a database beside
  the sites already on that box. A new instance keeps the demo separate, and CloudFront gives HTTPS
  without owning a certificate, which the session cookie requires because it is marked Secure.
- **By:** owner, 2026-09-20 · **Reversible:** yes; the teardown is one list of commands
- **Revisit when:** the demo needs to survive a restart, or the review is over and it comes down.
- **Supersedes:** none
- **Superseded by:** D-25 on 2026-10-16: the demo was torn down

### D-22 · The submission is published as a single commit

- **Decision:** the repository is published with one commit; the per-step history stays local and
  is not pushed. The build log carries the record of each step instead, and its commit citations
  were removed.
- **Options:** publish the real history after rewriting the harness wording it carried; publish one
  commit.
- **Why:** the owner's call: the work was local, and one commit is the simplest thing to hand over.
  The cost, stated before doing it, is that the trail of small commits and test-first fixes is no
  longer visible; the build log now carries that story.
- **Evidence:** the trees were compared before and after: the same tree hash and the same 376
  files, so the published commit carries exactly what the build produced.
- **By:** owner, 2026-09-20 · **Reversible:** no, once the local history is gone
- **Revisit when:** the project continues after the submission, when normal history resumes.
- **Supersedes:** none
- **Superseded by:** D-26 on 2026-10-16: normal history resumed after the tag `v0.1.0`

### D-21 · Step 8 is designed, not built

- **Decision:** exploratory questions answered by model-written SQL behind a server-side gate
  (A-X06) are not built. The design, with the other ideas left out of scope, is written in
  `50-designs/designed-not-built.md`.
- **Options:** build it as the last step; leave it out silently; leave it out and write the design.
- **Why:** it is the riskiest feature in the product and the least demanded: the typed catalogue
  answers every analyst story in the spec. Writing the design shows the thinking and costs an hour
  instead of a day.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** staff ask questions the metric catalogue cannot answer.
- **Supersedes:** none

### D-20 · The analyst's metric catalogue, and charts from one library loaded on demand

- **Decision:** the analyst answers from ten metrics (loans, returns, active and overdue loans,
  unique borrowers, new members, late-return rate, average loan days, share of copies on loan,
  titles not borrowed), eight groupings (category, book, author, month, year, weekday, the year
  members joined, or none), four filters, ten period presets or explicit dates, and two comparisons
  (the previous equivalent period, the same period last year). The server computes every total,
  share and change. Charts use recharts, loaded only when an answer has a chart.
- **Options:** a larger catalogue with ratios per member and per copy; a smaller one of counts
  only. For charts: hand-drawn SVG; a charts library in the main bundle; a charts library loaded on
  demand.
- **Why:** these metrics answer the questions the product spec names (A-X01 to A-X04) and the
  patterns the demo data carries, and each one is a fixed, tested query. Loading the library on
  demand keeps it out of the first page load: measured 2026-09-19, the chart code is a separate
  369 kB file and the main file grew by 3.7 kB.
- **By:** owner, 2026-09-19 · **Reversible:** yes; a metric is one entry in the catalogue
- **Revisit when:** staff ask questions the catalogue cannot answer (A-X06 is the planned route).
- **Supersedes:** none

### D-19 · The Copilot's default model is google/gemini-3.8-flash through OpenRouter

- **Decision:** `COPILOT_MODEL` defaults to `google/gemini-3.8-flash`; any OpenRouter model with
  tool support can replace it through configuration.
- **Options:** chosen on 2026-09-19 from OpenRouter's public model list (447 models, 378 with tool
  support): flagship models at about $2 / $10 per million input / output tokens, this model at
  $0.75 / $3.75, and lighter models at about $0.20 / $1.20.
- **Why:** current, strong at multi-step tool use, and a typical turn costs well under a cent.
  Measured live on 2026-09-19: catalog discovery, availability, a member's own loans and a declined
  reservation request all answered correctly in about 6 seconds per turn, with multi-round tool
  calls working.
- **By:** owner, 2026-09-19 (delegated) · **Reversible:** yes, one setting
- **Revisit when:** answer quality or latency disappoints in the demo, or pricing changes.
- **Supersedes:** none

### D-18 · Catalog search uses trigram matching

- **Decision:** search matches title, author and member names with case-insensitive substring
  matching, served by PostgreSQL `pg_trgm` GIN indexes; ISBN matches on normalized digits.
- **Options:** PostgreSQL full-text search; trigram matching; an external search engine.
- **Why:** full-text search matches whole words and stems, so "herb" does not find "Herbert" and
  ISBN fragments do not match at all. Trigram indexes make partial matches fast, stay inside
  PostgreSQL, and suit short fields like titles and names.
- **By:** owner, 2026-09-19 · **Reversible:** yes, behind the catalog service
- **Revisit when:** descriptions need to be searched by meaning, or the catalog grows past what
  substring matching ranks well.
- **Supersedes:** none

### D-17 · Data posture is demo

- **Decision:** the project runs in demo posture. Security and robustness hardening that is not
  required by the product spec is recorded as a `demo-debt` line in `99-pending.md` instead of
  blocking a step.
- **Options:** demo; production.
- **Why:** a time-boxed take-home with generated data and no real users. The core controls
  (server-side authorization, confirmation before AI writes, sessions, input validation) are in
  the spec and are built regardless.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** the product would hold real member data.
- **Supersedes:** none

### D-16 · The harness and knowledge base ship beside the application

- **Decision:** one repository. The application is in `repo/`; the AI working harness
  (`.claude/`) and this knowledge base (`docs/knowledge-base/`) are committed beside it, so a reader
  can see how the project was built. `working/` stays git-ignored scratch.
- **Options:** keep the harness private and ship only the application; ship both in one repository.
- **Why:** the brief explicitly allows AI tools. Showing the guardrails, the decision log and the
  product spec is evidence of how the work was controlled, which a bare repository cannot show.
- **By:** owner, 2026-09-19 · **Reversible:** yes, by removing the folders before publishing
- **Revisit when:** publishing, if the harness turns out to distract from the product.
- **Supersedes:** none

### D-15 · No separate code-review stage

- **Decision:** a step is done when `bash .claude/tools/verify.sh --full` is green and a
  `/test-guide` walk of the running app has been recorded. There is no separate review pass.
- **Options:** a fresh-context review per step; a second-model review; deterministic checks plus a
  local walk.
- **Why:** speed on a time-boxed solo build. Deterministic checks (lint, types, tests, build) and a
  guard against weakened tests carry correctness; the reviewers of the submission are the review.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** a step touches authorization or AI writes and a defect slips through the checks.
- **Supersedes:** none

### D-14 · Deliver in value order; publish and deploy at the end

- **Decision:** build in the order of section 4 of the product spec. Every step ends runnable,
  tested and documented, so work can stop after any step. Publishing to GitHub and deploying are
  end tasks.
- **Options:** milestone order from the original plan (all polish before any AI); value order.
- **Why:** the owner may stop the build at any point; a stop mid-week should leave the highest-value
  product possible, which includes a working Copilot before the polish items.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** the time budget changes.
- **Supersedes:** none
- **Superseded in part by:** D-26 on 2026-10-16: value order still holds for each new step; the end tasks are done

### D-13 · ISBN lookup and cover images join the scope

- **Decision:** adding a book can prefill title, author and year from an ISBN, and books show a
  cover image, using a public book metadata service (E17).
- **Options:** manual entry only; deterministic lookup; AI-generated metadata.
- **Why:** cheap, visibly more usable, and deterministic data beats generated data (L10).
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** the external service is unreliable during the demo; the form must work without it.
- **Supersedes:** none

### D-12 · One active loan per copy is enforced by the database

- **Decision:** a partial unique index on loans (copy) where the loan is not returned.
- **Options:** an application-level check only; a database constraint.
- **Why:** two staff borrowing the same copy at the same moment must not both succeed; only the
  database can guarantee that. The service turns the violation into a clear conflict error.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** never expected.
- **Supersedes:** none

### D-11 · Language models are reached through OpenRouter

- **Decision:** one OpenAI-compatible client pointed at OpenRouter; the model is a configuration
  value. The product works fully without a key: the Copilot then shows as unavailable.
- **Options:** a single vendor's API; a gateway to many models.
- **Why:** one key reaches every major model, so the model can be chosen per face on quality and
  cost without code changes.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** a required feature (for example strict structured output) is missing for the
  chosen model through the gateway.
- **Supersedes:** none

### D-10 · Demo data is generated from reader personas: three years of history

- **Decision:** a deterministic generator produces the catalog, members and three years of loan
  history. Members are drawn from reader personas (for example students, software professionals,
  retirees, parents, casual readers), each with its own favourite categories, borrowing rhythm,
  seasons and punctuality. Trends come from the personas' behaviour and from how the member mix
  changes over time; nothing is planted, and there is no answer key.
- **Options:** a handful of hand-typed rows; generated history with planted patterns and an answer
  key; persona-driven generated history.
- **Why:** analytics over twenty rows is meaningless, and persona-driven history reads like a real
  library to a reviewer. An answer key and evaluation scaffolding would cost time without adding
  product value (owner, 2026-09-19).
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** the generator becomes more work than the features it supports.
- **Supersedes:** the earlier wording of this entry (planted patterns with an answer key), revised
  the same day at the owner's request

### D-09 · Forecasts only with enough history, otherwise an honest refusal

- **Decision:** the analyst forecasts only when the series has 24 months to forecast from and
  enough later months to test the method on (32 for a three-month forecast), shows
  a range measured by testing the method against past months, and otherwise explains what it has,
  what it would need, and offers the trend instead (A-X05).
- **Options:** always draw a forecast; never forecast; forecast conditionally.
- **Why:** a forecast over six weeks of data is decoration. Knowing when not to forecast is the
  stronger product behaviour, and the generated history makes a real forecast possible.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** the seed history changes length.
- **Supersedes:** the original plan's "forecasting later" (L11)

### D-08 · The analyst answers through typed metric queries, not generated SQL

- **Decision:** the model chooses from a catalogue of metrics, groupings, filters, periods and
  comparison periods; the server runs fixed, parameterised queries; every number in the answer must
  come from the results. Generated read-only SQL behind a server-side gate is a later, labelled
  "exploratory" extension (A-X06), never the default.
- **Options:** text-to-SQL first; typed queries first.
- **Why:** typed queries are safe by construction, testable with exact expected answers, and make
  follow-ups and period comparisons simple parameter changes. Users never see or provide SQL either
  way.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** common questions fall outside the catalogue.
- **Supersedes:** none

### D-07 · The Copilot's safety rules are product rules

- **Decision:** the Copilot acts only through the same service layer and permission checks as the
  UI. The signed-in identity comes from the session, never from the model. Writes execute only when
  the user confirms a server-prepared proposal through a one-time, user-bound, short-lived token.
  AI actions are recorded in activity history. Numbers in answers come only from tool results.
  No destructive actions.
- **Options:** a chatbot with broad tools; a narrow, permission-aware tool layer.
- **Why:** the Copilot must be safe to demonstrate and easy to reason about; each rule removes a
  class of failure rather than relying on prompt wording.
- **By:** owner, 2026-09-19 · **Reversible:** no, without changing the product's promise
- **Revisit when:** never expected.
- **Supersedes:** none

### D-06 · One Copilot module with three faces

- **Decision:** one AI module; a face is a system prompt, a tool set and a permission scope.
  Members get the member face. Staff get the staff face and the analyst face in one panel.
- **Options:** three separate assistants; one module with role-scoped faces; a third management role.
- **Why:** the shared engine is built once and tested once; two roles stay two roles.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** a real management persona needs to be separated from staff.
- **Supersedes:** none

### D-05 · Google sign-in plus demo sign-in; server-side sessions

- **Decision:** Google sign-in through OpenID Connect, with server-side sessions in an HttpOnly
  cookie. A configuration flag enables one demo sign-in button per role, clearly labelled. Google
  users become Members unless their address is on the staff list.
- **Options:** Google, Microsoft, both; tokens held in the browser; server-side sessions.
- **Why:** a reviewer must be able to test both roles without an account from us. A same-origin
  application does not need tokens in the browser, and a session can be revoked. The demo buttons
  ask for no password because the product has no passwords at all: identity comes from Google, and
  the two demo accounts are shared accounts holding no personal data, so a password would protect
  nothing and add a credential to store, reset and leak. Everything after the button is the real
  path: the same session, cookie rules and permission checks.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** a second identity provider is required.
- **Supersedes:** none

### D-04 · FastAPI and Postgres, with the React app served from the same container

- **Decision:** Python 3.12 with FastAPI, async SQLAlchemy and Alembic on Postgres; a React
  single-page app (Vite, TypeScript, Tailwind, shadcn-style components, TanStack Query) built into
  the same image and served by the API from the same origin.
- **Options:** a full-stack Next.js application; a separately hosted frontend; this split.
- **Why:** one origin means cookie sessions without cross-site cookies or CORS; one image is one
  deployment; Python gives the AI layer the most mature tooling; typed models and migrations keep
  the data layer honest.
- **By:** owner, 2026-09-19 · **Reversible:** costly after step 1
- **Revisit when:** server-side rendering becomes a requirement.
- **Supersedes:** none

### D-03 · Borrow and Return are the product's words

- **Decision:** the UI says Borrow (check out) and Return (check in). The README maps the brief's
  reversed wording to these.
- **Options:** follow the brief's wording; use standard terms.
- **Why:** the brief's wording is reversed from standard library usage; repeating it would confuse
  every user.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** the brief's authors say otherwise.
- **Supersedes:** none
- **Changed on 2026-10-16 (D-26):** the README no longer maps the brief's wording; Borrow and Return stay

### D-02 · Two roles: Staff and Member

- **Decision:** exactly two roles. Management questions are served to Staff (D-06).
- **Options:** two roles; a matrix of staff roles.
- **Why:** real authorization with two roles is worth more than a role matrix nobody exercises.
- **By:** owner, 2026-09-19 · **Reversible:** yes
- **Revisit when:** a feature needs a permission Staff should not all have.
- **Supersedes:** none

### D-01 · The product boundary

- **Decision:** a single library; a Book separate from its Copies; a Loan links a Member and a
  Copy; availability is derived from active loans; loan history is kept; records with history are
  archived, not deleted. The out-of-scope list in the product spec is binding.
- **Options:** a status toggle on a book record; a circulation model.
- **Why:** the circulation model is what makes the product believable, at modest cost.
- **By:** owner, 2026-09-19 · **Reversible:** costly after step 1
- **Revisit when:** a second library or reservations are requested.
- **Supersedes:** none
