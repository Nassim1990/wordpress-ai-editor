# Gap Analysis — WordPress Control Server

Analysis of `WP_Claude_MCP_Server_Spec.md`, recalibrated for an **internal,
single-operator** tool (compliance / Law 25 concerns dropped per scope).

The spec is strong on the conceptual layer: the transport/execution split, the
R0/R1/R2 tiering, serialization-safe `search-replace`, and the
render→inject→commit→re-render styling loop are all correct for this fleet. The
gaps are almost all in the **operational, security, and feasibility** layers.

## Resolved in scope

- **Compliance / Law 25** — out of scope; this is an internal system.
- **MCP server operator auth (#1)** — softened to "private network + token";
  no multi-user identity needed.
- **Operator attribution (#3)** — moot with a single operator.

## Critical (safety) — still in force

| # | Gap | Why it matters | Status in this scaffold |
|---|---|---|---|
| 2 | **R1 "confirm" had no defined actor.** If Claude proposes *and* confirms, the gate is fake. | This is the difference between gated and not. | **Addressed.** Pluggable `Approver` (in-chat confirm-token, default; dev-auto). The operator must relay the plan's token to apply — Claude cannot self-issue approval. |
| 6 | **Concurrency & locking.** No per-site mutex; interleaved plans can corrupt. | Two writes to one site race. | **Addressed in spine.** Per-site advisory lock acquired across plan→apply. |
| 7 | **Plan drift at apply time.** TTL stops stale plans but not a target changed out-of-band between plan and apply. | Client edits in wp-admin between plan and apply. | **Addressed.** Plans store a target hash; `apply_plan` re-checks it. |
| 8 | **Rollback asserted, not engineered.** "Single follow-up call" — by whom, when, on partial failure? | Mid-apply failure leaves inconsistent state. | **Designed.** Plans carry `preflight_backup_ref`; apply is wrapped so a failure records the rollback reference. (Write tools land in later steps.) |
| 9 | **Backup granularity vs cost.** Full DA account backup before every R2 op is slow/heavy and can't roll back one table. | Reseller storage + time. | **Designed.** Backup tier is a plan field (`file` / `db` / `account`) matched to the op. |

## Feasibility (validate before building writes)

| # | Gap | Action |
|---|---|---|
| 10 | **SSH + WP-CLI + raw DB on CrocWeb reseller is unvalidated** — yet it's the "workhorse" backend. | **`spike/crocweb_probe.sh`** — run against one account first. |
| 11 | **DirectAdmin API scope on a reseller plan** (provision/restore/DNS may need admin). | Probed by the spike. |
| 12 | **DNS may live at Cloudflare**, not DA → `manage_dns` is a silent no-op. | Registry has a `dns_provider` column; record per site. |
| 13 | **SSH firewall allowlisting** — the server's IP may need whitelisting per account. | Probed by the spike (connectivity check). |

## Architectural — the headline feature

| # | Gap | Status |
|---|---|---|
| 5 | **No fleet/batch operations.** Every tool takes one `site`; the reason this project exists is doing things across 40 sites. | **Noted for a later step.** The gating middleware + plan store are designed so a batch plan can wrap N per-site plans with aggregate approval and partial-success reporting. |

## Operational

| # | Gap | Status |
|---|---|---|
| 14 | **No test/sandbox strategy** for a server that drives prod. | Registry supports an `active`/test flag; SQLite store makes the spine testable now; `pytest` suite included. |
| 15 | **No post-write health check.** Generalize the styling loop's step-5 verify to all writes. | Designed: apply flow has a post-apply verify hook (wired when write tools land). |
| 16 | **Capability/version drift; tools assume deps (AIOSEO, mcp-adapter).** | `capabilities`/`get_site` health ping; tools degrade when a dep is absent. |
| 17 | **No scheduling** (off-peak maintenance windows). | Future; out of scope for the spine. |

## Smaller notes

- `find_content` full-text via SQL `LIKE` over serialized/shortcode content is
  unreliable — surfaced as a documented limitation, REST is primary.
- `render_page` for auth-required pages isn't addressed (later, with Playwright).
- Single Hetzner Playwright box needs a browser-pool cap (later).

## Decisions taken in this scaffold (override-able)

- **Confirm channel:** pluggable `Approver`. The operator works in **Claude
  Cowork** (interactive chat), so the default is **in-chat `chat_token`** — the
  operator approves the plan inline and Cowork's own per-call tool-approval
  prompt is a second layer. `auto` is dev-only. (A future out-of-band approval
  dashboard can plug in via the same interface; none is implemented today.)
- **REST backend (open decision #3):** for **R0 reads**, call the WP REST API
  directly (no per-site `mcp-adapter` plugin dependency needed for read-only).
  Revisit for write tools.
- **Store:** `sqlite` for dev, `supabase` for prod (migrations in `migrations/`).
