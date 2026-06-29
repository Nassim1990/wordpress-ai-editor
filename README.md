# wpctl — WordPress Control Server

A Claude-driven MCP control layer for managing a fleet of self-hosted WordPress
sites on CrocWeb / DirectAdmin. Sites are addressed by friendly slug, reads are
free, writes are gated, and destructive actions are backed up before they run.

See [`docs/WP_Claude_MCP_Server_Spec.md`](docs/WP_Claude_MCP_Server_Spec.md) for
the full design, and [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) for the
analysis that shaped this scaffold.

## Status

This repository currently contains the **foundation** (spec build-order steps
1–early): the cross-cutting spine and the read tools, plus the gating mechanism
that everything else hangs off.

Implemented:

- **Spine** — site registry, plan store, and audit log behind a `Store`
  interface, with a runnable **SQLite** backend for local dev and **Supabase**
  SQL migrations for production.
- **Gating middleware** — generic R0 / R1 / R2 enforcement. The **confirm
  channel is pluggable** (`Approver` interface). The operator chats with Claude
  in **Claude Cowork**, so the default is **in-chat confirmation**
  (`chat_token`) — the operator approves a plan inline, and Cowork's own
  per-call tool-approval prompt is a second layer. A dev auto-approver exists
  for local testing. (A future out-of-band approval dashboard can plug in via
  the same interface; none is implemented today.)
- **Secret resolution** — refs (`ssh_key_ref`, `app_password_ref`, …) resolve to
  real material server-side and are never returned to Claude.
- **R0 read tools** — `list_sites`, `get_site`, `get_option`, `db_select`
  (SELECT-only guard), `find_content`, `get_content`, `list_files`, `read_file`.
- **Executors** — SSH/WP-CLI runner and WP REST client (lazy-imported so the
  package imports without their deps installed).
- **Feasibility spike** — `spike/crocweb_probe.sh`, a read-only probe you run
  against one CrocWeb account to validate SSH, WP-CLI, raw DB access, and the
  DirectAdmin API scope **before** building the write tools.

Not yet built (later spec steps): R1/R2 write tools (`search_replace`,
`write_file`, plugin/theme lifecycle), DirectAdmin hosting tools, Playwright
rendering, and fleet/batch fan-out.

## Quick start (local dev, no live sites needed)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # WPCTL_STORE=sqlite, WPCTL_APPROVER=auto
python -m wpctl.seed examples/sites.example.csv   # seed the registry
pytest                        # store + gating tests run with no external deps
python -m wpctl.server        # start the MCP server (stdio)
```

## Run the feasibility spike (before building writes)

```bash
spike/crocweb_probe.sh --ssh user@host --wp-path ~/domains/example.com/public_html \
  --da-host https://server.crocweb.com:2222 --da-user reseller
```

It only reads; it changes nothing. See [`spike/README.md`](spike/README.md).

## Configuration

All config is via env vars (see `.env.example`). Key choices:

| Var | Values | Meaning |
|---|---|---|
| `WPCTL_STORE` | `sqlite` \| `supabase` | Registry / plans / audit backend |
| `WPCTL_APPROVER` | `chat_token` \| `auto` | R1/R2 confirm channel (default `chat_token` for Cowork) |
| `WPCTL_SECRETS` | `env` | Secret resolver (env-based for dev) |

`WPCTL_APPROVER=auto` approves writes with no human — **dev only**. Production
should use `chat_token`.
