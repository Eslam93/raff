# Project rule: Raff

Raff (رف, "shelf") is a library system for small community libraries, and the owner's own project
(D-26). It began as a one-day build, tagged `v0.1.0`.

Facts a fresh session would otherwise get wrong. Dated where they can change.

**The one fact that matters most:** the application lives in `repo/`. Everything beside it at the
root (`.claude/`, `docs/knowledge-base/`, `working/`) is how the project is built and documented.
The product definition is `docs/knowledge-base/10-product/product-spec.md`; read it before any
feature work. Scope questions default to **no** unless the spec says yes.

## Layout

| Path | What |
|---|---|
| `repo/backend/` | FastAPI API: Python 3.12, uv, async SQLAlchemy, Alembic, Postgres |
| `repo/frontend/` | React SPA: Vite, TypeScript, Tailwind 4, shadcn-style components, TanStack Query |
| `repo/` (root files) | the Dockerfile that builds one image (API serving the built SPA) and the compose file |
| `docs/knowledge-base/` | product spec, decisions (`decisions.md`), open items (`99-pending.md`) |
| `working/` | private scratch, git-ignored. Never link to it from anything committed |

## Branches and delivery

- One repository, `Eslam93/raff`, trunk `main`. Since 2026-10-16 history is normal commits (D-26):
  each task is cut from `main` on its own branch and lands through a pull request the owner merges.
  Never force-push `main`. The first version is the tag `v0.1.0`.
- Nothing is deployed as of 2026-10-16: the AWS demo was torn down (D-25), and hosting on the
  owner's own machine is still to be decided.
- Delivery is value-ordered (D-14): every step ends runnable, tested and documented, so work can
  stop after any step. Do not start a step before the previous one is green.

## Commands

As of 2026-09-19 (update when they change):

- Backend, from `repo/backend`: `uv sync` · `uv run ruff check .` · `uv run ruff format --check .` ·
  `uv run mypy app` · `uv run pytest` · `uv run alembic upgrade head` · run with
  `uv run uvicorn app.main:create_app --factory --reload`
- Frontend, from `repo/frontend`: `pnpm install` · `pnpm lint` · `pnpm typecheck` · `pnpm test` ·
  `pnpm build` · dev server `pnpm dev` (it proxies API calls to port 8000)
- `uv` and `pnpm` must be on PATH (`verify.project.sh` falls back to `python -m uv`)
- Local Postgres: `docker compose up -d db` in `repo/` publishes it on `127.0.0.1:55432`, which is
  the backend's default `DATABASE_URL`. `REQUIRE_DB=1` makes a missing database fail the tests
- Whole stack: `docker compose up --build` in `repo/`, then http://localhost:8000
- Demo library: `uv run python -m app.seed --reset` (or `docker compose exec app python -m app.seed
  --reset`); refused in production
- Copilot: `OPENROUTER_API_KEY` in git-ignored `repo/.env`; `COPILOT_FAKE_MODEL=true` runs a scripted
  model for local checks and is refused in production
- Everything: `bash .claude/tools/verify.sh --full` runs the harness checks plus
  `.claude/tools/verify.project.sh` (lint, types, tests and build for both halves)

## How we work here

- **Data posture: demo** (D-17). Hardening shortcuts are `demo-debt` lines in `99-pending.md`.
- **No independent code review in this project's loop** (D-15). Done means `verify.sh --full`
  green plus a `/test-guide` walk of the running app.
- **AI rules are product rules** (D-07): the Copilot acts only through the same service layer and
  permission checks as the UI, never mutates without a user confirmation, and never states a number
  that did not come from a tool result.
- **Self-contained.** Nothing here references anything outside this folder.
- Commit messages end with the `Co-Authored-By: Claude` trailer (owner's choice, 2026-09-19).

## How steps run

Each step has an agreed brief with an outcome checklist and the exact API contract in
`working/step-N-*/brief.md`; `working/status.md` says where the build is. A step is done when the
gate is green, every checklist line was walked in a browser against the Docker stack, and the
README status, `99-pending.md` and decisions are updated.

## Terms: one name per concept

| Term | Means |
|---|---|
| Book | a title in the catalog (title, author, ISBN, category, year, description) |
| Copy | one physical copy of a book, with a copy code such as `CP-0001` |
| Member | a person who borrows; may or may not have a sign-in |
| Loan | a copy lent to a member, with a due date; active until returned |
| Borrow / Return | check out / check in, the standard library words (D-03) |
| Overdue | an active loan past its due date. Derived, never stored |
| Staff, Member | the only two roles |
| Activity | the append-only record of actions (who, what, when, and whether via the Copilot) |
| Copilot | the one AI module. Faces: member, staff, analyst. Staff see staff and analyst tools in one panel |
