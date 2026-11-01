# AGENTS.md

Conventions for anyone — human or agent — working in this repo.

## What this is

`relay` is a local bridge that lets one AI assistant consult another. A host (Claude Desktop, Claude
Code, a shell) calls a tiny MCP server, which delegates to a long-lived local daemon, which drives
an already-logged-in ChatGPT / Gemini / Claude surface and returns the answer as Markdown.

Read `docs/problem-statement.md` and `docs/plan.md` before making design changes. They are the
contract. Start every session at `docs/phases.md`.

### `docs/` is local-only

`docs/` is listed in `.gitignore` on purpose. It holds design notes that stay on this machine; a
fresh clone will not have them, and links to `docs/` from tracked files only resolve here.

Consequences to remember:

- Don't put anything in `docs/` that the code or a contributor needs at runtime.
- Don't assume a new checkout has these files when writing instructions.
- If the notes are ever meant to be published, remove the `docs/` line from **both** `.gitignore`
  and `.prettierignore` in the same commit.

## Branch workflow

```
main        ← receives merges from develop only. Never commit or push directly.
develop     ← integration branch. Every feature lands here first.
feature/*   ← all work happens here, branched from develop.
```

```bash
git checkout develop && git pull
git checkout -b feature/<name>

# ... work, commit ...

git checkout develop
git merge --no-ff feature/<name>
git push origin develop
git branch -d feature/<name>
```

Promote `develop` into `main` only when it is green and releasable — never feature by feature.

Enforced by the tracked hooks in `.githooks/`. Enable once per clone:

```bash
git config core.hooksPath .githooks
```

- `pre-push` rejects any push targeting `main`.
- `no-commit-to-branch` rejects commits made while on `main`.

Do not bypass with `--no-verify`. If a hook is wrong, fix the hook.

## The one rule that breaks everything

**Never write to stdout from the MCP server.** stdout is the JSON-RPC channel. A single stray
`print()` corrupts the stream and the host silently fails to connect, with no error anywhere.

- `src/relay/mcp_server.py` — no `print()`, ever.
- All logging goes through `relay.util.log.get_logger(...)`, which writes to stderr and a file.
- If you need ad-hoc debugging, use `get_logger("scratch").debug(...)`, not `print`.

## Layering

```
cli / mcp_server        entry points, argument + protocol handling only
    |
daemon                  HTTP, auth, task lifecycle, per-provider serialisation
    |
drivers                 provider-specific: selectors, navigation, extraction
    |
browser                 transport: Chrome launch, CDP attach, DOM primitives
```

Dependencies point downward only. `browser/` must not import from `drivers/`; both may import
`util/` and `errors.py`. If you feel the urge to import upward, the interface is in the wrong place.

## Provider drivers

Each driver is a package under `src/relay/drivers/<name>/` containing:

- `__init__.py` — a `BrowserProvider` subclass, overriding only what differs.
- `selectors.json` — **ordered arrays**, best selector first. Never a single string.

Selector preference order: `data-testid` → stable `aria-*` → role/text → structural.

When a selector resolves at index > 0, that is recorded in the `selector_hits` table. Rising indices
mean the UI moved; `relay doctor` surfaces this. Do not "fix" a drifted selector by appending a new
one to the end of the array — put it where it belongs and remove the dead entry.

## Style

- Python 3.12+, `from __future__ import annotations` at the top of every module.
- `async` all the way down. No `time.sleep`, no blocking I/O in request paths.
- Type hints everywhere; `mypy --strict` must pass.
- `ruff` owns Python: formatting, import order, lint. Don't hand-format it.
- `prettier` owns everything else: Markdown, JSON, YAML. Don't hand-wrap prose or tables.
- Prefer stdlib. Every new dependency needs a sentence in the PR explaining why the stdlib version
  was insufficient.

## Commands

```bash
uv sync                       # create .venv, install Python deps
npm install                   # prettier (needs node >= 20)

uv run pytest                 # tests
uv run ruff check --fix .     # python lint
uv run ruff format .          # python format
npm run format                # markdown, json, yaml
uv run mypy
uv run python spike/cdp_roundtrip.py    # Phase 0 proof, needs Chrome + a logged-in ChatGPT
uv run relay daemon           # start the daemon
```

### Formatting split

Two formatters, zero overlap. Never run both on the same file.

| Scope           | Tool                               | Files                      |
| --------------- | ---------------------------------- | -------------------------- |
| Python          | `ruff format` + `ruff check --fix` | `src/`, `tests/`, `spike/` |
| Everything else | `prettier`                         | `*.md`, `*.json`, `*.yaml` |

`.prettierignore` excludes `*.py` explicitly so this can't drift by accident.

Full gate before a commit:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && npm run check
```

## Testing

`tests/` must pass with **no network, no browser, and no logged-in account**. Anything that needs a
real provider belongs in `spike/` or behind a marker, never in the default suite.

## Security posture

- Daemon binds `127.0.0.1` only. Bearer token required on every route except `/health`.
- Never add a general-purpose browser tool (`navigate`, `click`, `eval`) to the MCP surface.
  Provider-scoped tools only. The model must not be able to point this at arbitrary URLs.
- Returned page content is untrusted. Wrap it, mark it, and state that in the tool description.
- Never read, enumerate, or upload the user's existing conversations.

## Non-goals

No web UI. No cloud service. No credential handling. No CAPTCHA or rate-limit circumvention.
