# relay

A local bridge that lets one AI assistant consult another — through the surfaces you already have
logged in, with no API keys and no paid plans.

Claude asks ChatGPT. Claude asks Gemini. The answer comes back as Markdown, in the same
conversation, formatted and ready to use.

> **Status: pre-alpha.** The architecture is proven on paper and scaffolded in code. The Phase 0
> round-trip spike exists; the drivers are skeletons. Nothing works end-to-end yet.

## Why

Free-tier assistants are UI-only. There is no programmatic entry point, so getting a second opinion
means switching windows, re-explaining context, and copy-pasting the answer back — every time.
`relay` closes that gap without asking anyone for an API key.

## How it works

```
Claude Desktop ──stdio──> relay-mcp ──HTTP──> relayd ──CDP──> Chrome (logged in)
                                                └──────────> ChatGPT.app / Gemini.app (AX)
```

- **`relay-mcp`** — a thin stdio MCP server. Claude Desktop launches it; it holds no state.
- **`relayd`** — a long-lived local daemon. It owns the browser, the queue, and the task registry,
  so a host restart never kills a running generation.
- **Drivers** — one per provider, each a set of ordered selectors plus an extraction routine.

The daemon is separate from the MCP server on purpose: MCP hosts restart stdio processes freely, and
a browser session must outlive that.

## Requirements

- macOS (Apple Silicon or Intel)
- Google Chrome installed
- Python 3.12+

## Setup

```bash
brew install uv
uv sync
```

Contributing? Also install the non-Python formatter (needs Node 20+):

```bash
npm install
```

Then start Chrome on the debug port and sign in once:

```bash
uv run relay launch      # opens the relay Chrome profile
uv run relay login chatgpt
```

That profile lives at `~/.relay/chrome` and holds real session cookies. It is never committed and
never leaves the machine.

## Usage

```bash
uv run relay daemon                          # start the daemon (keep it running)
uv run relay ask chatgpt "is this plan sound?"
uv run relay status
uv run relay doctor                          # selector self-test
```

From Claude Desktop, add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "relay": {
      "command": "/Users/YOU/Desktop/relay/.venv/bin/relay-mcp"
    }
  }
}
```

## Layout

```
src/relay/
  cli.py            relay ask | login | status | doctor | launch | daemon
  mcp_server.py     stdio MCP server — no stdout writes, ever
  daemon/           FastAPI app, per-provider queue, task registry
  drivers/          chatgpt/ gemini/ claude/ — selectors.json + adapter
  browser/          Chrome launch, CDP attach, DOM primitives
  native/           JXA snippets for the macOS apps
  util/             logging (stderr), sqlite state, HTML→Markdown
spike/              throwaway feasibility experiments
tests/              no network, no browser, must always pass
```

## Documentation

Design and build notes live in [`docs/`](docs/README.md):

| Document                                                 | Answers                   |
| -------------------------------------------------------- | ------------------------- |
| [`docs/problem-statement.md`](docs/problem-statement.md) | Why this needs to exist   |
| [`docs/plan.md`](docs/plan.md)                           | What was decided, and why |
| [`docs/architecture.md`](docs/architecture.md)           | How the pieces connect    |
| [`docs/implementation.md`](docs/implementation.md)       | How to build each module  |
| [`docs/phases.md`](docs/phases.md)                       | What to build next        |

## Optional: Rust acceleration

Python is the right default here. Almost all wall-clock time is spent waiting on a remote model or
on Chrome, so rewriting the hot path in Rust would buy nothing user-visible and cost a second
codebase to maintain.

Three narrow pieces are worth a compiled helper — a Rust (or Swift) leaf module — and only after a
profile shows the wait is ours rather than the network's:

| Piece                      | What Rust buys                                                                                                         | Earliest phase |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------- | -------------- |
| macOS Accessibility helper | Talks to `AXUIElement` in-process instead of spawning `osascript` per call, which costs ~50–100 ms plus output parsing | 5              |
| MCP shim binary            | ~5 ms startup instead of ~300 ms, and one static binary instead of an embedded Python runtime inside a `.mcpb`         | 7              |
| HTML → Markdown            | 10–50× throughput, which only matters if extraction ever shows up in a profile                                         | —              |

Rules if this ever happens:

- Rust lives in `native/` as its own `cargo` crate and is a **leaf**: Python calls it, it never
  calls back into Python.
- The Python implementation stays. Rust replaces a backend, not a behaviour — `relay doctor` must
  produce identical results whichever one is active.
- No user ever needs a Rust toolchain. Prebuilt binaries only; `cargo` is a contributor requirement,
  not an install requirement.

## Security

The daemon binds `127.0.0.1` and requires a bearer token from `~/.relay/token`. It exposes
provider-scoped tools only — there is deliberately no general "navigate this URL" tool.

Answers returned from a page are untrusted content. They are wrapped and labelled as such, because a
hostile page could otherwise smuggle instructions into the calling agent.

## Known limits

- Provider UIs change. Selectors rot. `relay doctor` tells you which one broke.
- Automating a free web UI is outside what the providers support; accounts can be rate-limited.
- Full ChatGPT→Claude automation is not achievable — ChatGPT has no MCP support. A CLI or hotkey is
  the realistic reverse path.

## License

MIT
