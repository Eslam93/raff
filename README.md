# Raff

[![CI](https://github.com/Eslam93/raff/actions/workflows/ci.yml/badge.svg)](https://github.com/Eslam93/raff/actions/workflows/ci.yml)

Raff (رف, "shelf") is a library system for small community libraries: a school library, a mosque or
church library, an office or coworking bookshelf, a neighbourhood book corner. Staff keep the
catalog and lend books; members find books and keep track of what they have borrowed. It runs on
one small machine with Docker, and it has an AI Copilot that works only through the library's own
actions and never makes up a number.

**Try it: https://raff.eslamhamed.com** Press "Sign in as staff" or "Sign in as member". Both demo
accounts share one generated library, so anything you change there is visible to the next visitor.

## What it does

- **A catalog of books and their copies.** A book is the title; each physical copy has its own code
  (such as `CP-0001`). "Look up" fills a new book's details from its ISBN, and covers appear on
  their own. Search finds part of a title, an author or an ISBN.
- **Borrow and Return.** A circulation desk that works by copy code, due dates, overdue tracking,
  and the loan history of every book and member. Availability is worked out from the loans each
  time, so it is never out of date.
- **Holds and renewals.** When every copy of a book is out, a member joins the line for it from
  the book's page. A returned copy is set aside for the first person in line for three days, and
  the desk sees who it is for. Members renew their own loans, at most twice and not while someone
  is waiting for the book.
- **Two roles with their own screens.** Staff manage the catalog, members and circulation, and
  see a dashboard and an activity log. Members browse the catalog and see their own loans and
  history.
- **The Copilot,** a panel on every page:
  - Members ask it to find books and about their own loans.
  - Staff use it to look up members, loans, overdue items and copies. It also prepares a Borrow or
    a Return, and nothing happens until they press Confirm.
  - Staff ask it how the library is used and get a table, a chart, or a forecast computed from the
    data.

**Built to stay correct.** The same copy cannot be lent twice at once: the database allows one
active loan per copy, and a test races two real connections for it. A book with loan history is
archived, never deleted, so the history stays. Every action is recorded in an append-only activity
log, marked when it came through the Copilot.

## Run it

Requirements: Docker.

```bash
cd repo
docker compose up --build
```

That command keeps running and prints the logs, so load the sample library from a second terminal.
It is generated from reader personas: 286 real titles, about 490 copies, 200 members, and three
years of borrowing that ends today, so some books are out and a few are overdue. It takes a few
seconds:

```bash
cd repo
docker compose exec app python -m app.seed
```

Then open http://localhost:8000.

The seed only fills an empty library; `python -m app.seed --reset` replaces the library data (never
in production). The API's health check is at
http://localhost:8000/api/health and, outside production, its interactive documentation is at
http://localhost:8000/api/docs.

## Sign in

The sign-in page offers two demo accounts, one per role, so both can be tried without an account:
**staff** manage the catalog, members and circulation; **members** browse the catalog and see their
own loans and history.

**The demo buttons ask for no password, on purpose.** There is no password anywhere in Raff: the
two demo accounts are shared accounts that belong to nobody and hold no personal data, and one
button press signs you into one of them. Real accounts come from Google, which is the only way to
become a named user here, so Raff never stores, hashes, resets or emails a password. The demo
buttons are a setting (`DEMO_LOGIN_ENABLED`), off by default in production. Everything behind them
is the real thing: the same server-side session, the same cookie rules and the same permission
checks as a Google sign-in.

**Google sign-in (optional).** It appears on the sign-in page once a Google OAuth client is
configured:

1. In the [Google Cloud console](https://console.cloud.google.com/), pick or create a project and
   open **Google Auth Platform** (older consoles: APIs and Services, OAuth consent screen).
2. **Branding:** an app name and a support email. **Audience:** External. While the app is in
   Testing, add every Google address that should be able to sign in as a test user.
3. **Clients:** create a client of type **Web application** with the authorized redirect URI
   `http://localhost:8000/api/auth/google/callback`.
4. Put the client id and secret in `repo/.env` (Docker Compose reads it; use `repo/backend/.env`
   when running the API with uv):

   ```bash
   GOOGLE_CLIENT_ID=<client id>
   GOOGLE_CLIENT_SECRET=<client secret>
   STAFF_EMAILS=<addresses that should join as staff, comma-separated>
   ```

5. Restart with `docker compose up -d --build` and open http://localhost:8000/sign-in, using
   `localhost` as in the redirect URI. Addresses in `STAFF_EMAILS` join as staff the first time they
   sign in; everyone else joins as a member.

To run it for real people, also set `APP_ENV=production`, a random `SESSION_SECRET` of at least 32
characters, `PUBLIC_BASE_URL=https://<your domain>`, `DEMO_LOGIN_ENABLED=true` only if the demo
buttons should stay, and register `https://<your domain>/api/auth/google/callback` with Google.
Before a real library's members go in, read the `demo-debt` lines in the
[open items](docs/knowledge-base/99-pending.md): they are the shortcuts that are fine for sample
data and not for personal data.

## The Copilot

The Copilot needs an [OpenRouter](https://openrouter.ai/) API key; without one the panel says it is
unavailable and everything else works. Put the key in `repo/.env` and restart:

```bash
OPENROUTER_API_KEY=<key>
# COPILOT_MODEL=<any OpenRouter model with tool support; default google/gemini-3.8-flash>
```

It only uses Raff's own actions, with the signed-in person's permissions: it never acts on another
member's data, and declines what Raff does not offer, such as fines. It can tell a member where they
are in line for a book, and tell staff who is waiting; placing a hold or renewing is done on the
page. It is also held to its
figures: before a reply is sent, every run of digits in it must appear in a lookup result or in
what the person typed, or the reply is retried once and then replaced by the lookup results as
plain text.

For staff it can also prepare a Borrow or a Return ("Borrow The Hobbit for Maya Hassan"). It shows
the change as a card with Confirm and Cancel. The server stores the proposal for 10 minutes, only
the person who asked can confirm it, and only once. Confirming runs the same rules as the
circulation desk, and the activity history marks the action as made through the Copilot. When a
name matches several members, it asks which one.

Staff can also ask about how the library is used: "Which categories were borrowed most this
quarter?", then "Only among members who joined this year?", then "How does that compare with last
quarter?". The model never writes a database query: it fills in a typed request from a fixed list
of metrics, groupings, filters and periods, and the server runs a fixed query for it and computes
every total, share and change. Answers show a table, and a chart where one helps. "Forecast
borrowing for the next three months" gives each month with a likely range measured by testing the
method on past months; when the history is too short, too thin or too erratic, it says what it has
and what it would need, and shows the trend instead.

## What comes next

In this order. Imports are designed in
[Designed, not built](docs/knowledge-base/50-designs/designed-not-built.md); scanning is outlined
there and gets its full design when its turn comes.

1. **Scan at the desk.** A phone or laptop camera reads an ISBN or a copy's label, and staff print
   labels with a QR code for each copy.
2. **Import from a spreadsheet,** so a library does not type in its books one by one.

After those, an Arabic interface.

## Develop

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22.12 or newer with pnpm, Docker.

```bash
# database only, published on 127.0.0.1:55432
cd repo && docker compose up -d db

# API on http://localhost:8000
cd repo/backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --reload

# web app on http://localhost:5173, calling the API through the dev server
cd repo/frontend
pnpm install
pnpm dev
```

Every check in one command, from the repository root: `bash .claude/tools/verify.sh --full`
(backend lint, formatting, types and tests; frontend lint, types, tests and build).

## What is where

| Path | What |
|---|---|
| `repo/backend/` | FastAPI API: Python 3.12, async SQLAlchemy, Alembic, PostgreSQL |
| `repo/frontend/` | React web app: Vite, TypeScript, Tailwind CSS, TanStack Query |
| `repo/Dockerfile` | one image: the API serves the built web app from the same origin |
| `docs/knowledge-base/` | the product spec, the decision log, open items |
| `.claude/` | the AI working harness Raff is built with ([what is in it](.claude/README.md)) |
| `.github/workflows/` | CI: backend checks against a real PostgreSQL, frontend checks, image build |

## How it is built

Raff is built with an AI coding assistant working inside a small harness of rules, hooks and checks
(`.claude/`), with the owner deciding the product and every fork. The
[knowledge base](docs/knowledge-base/README.md) tells the story:

- [Build log](docs/knowledge-base/30-delivery/build-log.md): each step, what was agreed, built and
  verified, and what went wrong and how it was fixed.
- [How this was built](docs/knowledge-base/40-method/how-this-was-built.md): who decided what, the
  loop every step followed, and what is enforced mechanically.
- [Designed, not built](docs/knowledge-base/50-designs/designed-not-built.md): the roadmap, and how
  each idea would be built here: imports, letting the AI write database queries
  safely, further uses of AI under the same rules, and what production needs.
- [Product spec](docs/knowledge-base/10-product/product-spec.md),
  [architecture](docs/knowledge-base/20-architecture/system-overview.md),
  [decisions](docs/knowledge-base/decisions.md) and [open items](docs/knowledge-base/99-pending.md).

## Licence

[MIT](LICENSE). The first complete version is tagged `v0.1.0`.
