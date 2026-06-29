# WordPress Control Server: Build Spec

A Claude-driven control layer for managing 40+ self-hosted WordPress sites on CrocWeb / DirectAdmin, addressed by name through one connection, with reads free, writes gated, and destructive actions backed up before they run.

---

## 1. Purpose

Let Claude modify any client site in plain language without anyone touching wp-admin, SFTP, or a migration plugin. The operator describes the outcome, the server does the work, and the riskier the action, the more it slows down to preview and protect before acting.

Target fleet: Technocure client sites (Boucherie Beirut, jeconduis.com, B12 Burger, Levant Hall, Magic Vitres, U-Lease, and the rest), built largely on TheGem, WoodMart, Impreza, and WPBakery, hosted on CrocWeb reseller infrastructure with DirectAdmin.

---

## 2. Architecture

Two layers, kept separate. This is the core idea.

**Transport** is how Claude talks to the tools. This is MCP. Nothing is built from scratch here. The server is an MCP server that Claude (Desktop or Code) connects to once.

**Execution** is what actually changes WordPress. Four backends, each with different reach:

| Backend | Reach | Notes |
|---|---|---|
| WordPress REST API (`wp-json`) | Posts, pages, media, users, custom post types, plugin endpoints | Auth via Application Passwords. Clean and safe but cannot edit theme files, and page builder internals are awkward through it. |
| WP-CLI over SSH | Everything REST cannot do | File ops, serialization-safe `search-replace`, options, raw db queries, core/plugin/theme management. The workhorse. |
| DirectAdmin / CrocWeb API | Hosting level: sites, databases, DNS, SSL, cron, backups | Not content. Provisioning and recovery. |
| Headless browser (Playwright) | Renders pages to screenshots | Gives Claude eyes for styling and visual QA. |

The serialization point matters for this fleet specifically. TheGem and Impreza store layout and options as serialized data, and WPBakery stores shortcodes in post_content. `wp search-replace` walks serialized data and keeps its byte-length prefixes intact, which is why bulk text and URL changes route through WP-CLI and never through naive find-and-replace.

### Options considered

| Option | What it is | Verdict |
|---|---|---|
| A. Claude Code + SSH + WP-CLI | Claude SSHes in and runs WP-CLI. Zero infrastructure. | Use today for ad hoc work. Per-site, interactive, runs against prod unless pointed at staging. |
| B. Official WordPress MCP (`mcp-adapter` plugin + `@automattic/mcp-wordpress-remote`) | Structured REST tools, OAuth 2.1 / JWT / app password auth, respects WP capabilities. | Good as the REST execution backend. Bounded to REST, plugin to maintain per site. |
| C. Custom MCP server on Hetzner | One server wrapping all backends behind curated tools, with registry, gating, audit. | The agency-grade answer. This spec. |
| D. Anthropic API tool-calling app | Same backend as C, called from your own app instead of MCP. | The non-interactive sibling for automation or a dashboard. Reuses the C tool layer. |

Recommended path: build C, and let it call B's `mcp-adapter` as its REST content backend rather than reinventing content tools, while C adds the WP-CLI, DirectAdmin, and render tools that REST cannot cover.

---

## 3. Risk tiers and gating

Every tool declares a tier. The gating middleware enforces it generically, so tools only declare, they do not each reimplement safety.

| Tier | Meaning | Gate |
|---|---|---|
| R0 | Read. No change to the site. | None. |
| R1 | Reversible write. | Auto-snapshot (or native WP revision) plus a single confirm. |
| R2 | Destructive or irreversible. | `plan_*` returns a computed diff or dry-run result plus a `plan_id`. `apply_plan(plan_id)` executes after a mandatory pre-flight backup. Plans are single-use with a short TTL so the preview cannot drift from what applies. |

Every tool takes `site` (the registry slug). Credentials, SSH keys, and app passwords stay server-side and are never returned to Claude. Claude addresses sites by friendly slug only.

Because the deployment model is direct to production with gated writes, safety lives entirely in the gating and in mandatory pre-flight backups. There is no staging buffer to catch mistakes, so the rule is firm: anything destructive runs a dry-run or diff first, and only applies after an automatic backup.

---

## 4. Tool surface

### 0. Registry and resolution

| Tool | Inputs | Backend | Tier |
|---|---|---|---|
| `list_sites` | filter | Supabase | R0 |
| `get_site` | site | Supabase + live health ping | R0 |
| `capabilities` | site | REST | R0 |

### 1. Content (REST primary)

| Tool | Inputs | Backend | Tier | Gate |
|---|---|---|---|---|
| `find_content` | site, query, type, status | REST (WP-CLI db fallback for full text) | R0 | none |
| `get_content` | site, id | REST | R0 | none |
| `create_content` | site, type, title, body, status, meta | REST | R1 | confirm |
| `update_content` | site, id, partial fields | REST | R1 | confirm (WP keeps a native revision) |
| `set_seo` | site, id, AIOSEO fields | REST | R1 | confirm |
| `upload_media` | site, source url or ref, alt | REST | R1 | confirm |
| `manage_menu` | site, menu, item ops | WP-CLI | R1 | confirm |

### 2. Options and DB-safe (WP-CLI)

| Tool | Inputs | Backend | Tier | Gate |
|---|---|---|---|---|
| `get_option` | site, key | WP-CLI | R0 | none |
| `set_option` | site, key, value | WP-CLI | R1 | snapshot + confirm |
| `search_replace` | site, search, replace, tables, dry_run | WP-CLI | R2 | dry-run count, then plan/apply + backup |
| `db_select` | site, sql | WP-CLI | R0 | SELECT-only parser guard |
| `export_content` | site, scope | WP-CLI / WXR | R0 | none |

`search_replace` is what makes the page builders safe. It runs `wp search-replace` so serialized TheGem, Impreza, and WPBakery data keeps its byte-length prefixes intact, and the plan shows the affected row count before anything changes.

### 3. Theme and files (SSH / SFTP)

| Tool | Inputs | Backend | Tier | Gate |
|---|---|---|---|---|
| `list_files` | site, path | SSH | R0 | jailed to wp-content |
| `read_file` | site, path | SSH | R0 | jailed |
| `write_file` | site, path, content | SSH | R2 | diff preview, then plan/apply + file backup |
| `patch_file` | site, path, find, replace | SSH | R2 | diff preview, then plan/apply + backup |

File tools are path-jailed to the site's wp-content, so nothing can touch wp-config or escape the docroot.

### 4. Plugin and theme lifecycle (WP-CLI)

| Tool | Inputs | Backend | Tier | Gate |
|---|---|---|---|---|
| `list_extensions` | site | WP-CLI | R0 | none |
| `toggle_plugin` | site, slug, action | WP-CLI | R1 | confirm |
| `install_extension` | site, slug or zip, type | WP-CLI | R2 | plan/apply + backup |
| `update_extension` | site, slug or all | WP-CLI | R2 | plan/apply + backup |

Keep `update_extension` strict. The premium themes (TheGem, WoodMart, Impreza) are exactly where a blind update breaks a layout, so the plan surfaces version deltas and the backup is non-negotiable.

### 5. Maintenance and diagnostics

| Tool | Inputs | Backend | Tier | Gate |
|---|---|---|---|---|
| `site_health` | site | WP-CLI / REST | R0 | none |
| `flush_cache` | site | WP-CLI (LiteSpeed) | R1 | confirm |
| `flush_rewrites` | site | WP-CLI | R1 | confirm |

### 6. Hosting (DirectAdmin API)

| Tool | Inputs | Backend | Tier | Gate |
|---|---|---|---|---|
| `create_backup` | account | DA API | R1 | confirm (also the pre-flight engine) |
| `list_backups` | account | DA API | R0 | none |
| `restore_backup` | account, backup id | DA API | R2 | plan/apply + typed confirm |
| `manage_dns` | account, record ops | DA API | R2 | plan/apply + typed confirm |
| `manage_ssl` | account, domain | DA API | R2 | plan/apply |
| `provision_site` | domain, plan | DA API + WP-CLI install | R2 | plan/apply |

`create_backup` does double duty. It is a tool Claude can call, and it is what the R2 middleware fires automatically before any destructive op, stashing the backup reference in the plan so a rollback is a single follow-up call.

### 7. Rendering and visual QA (Playwright)

| Tool | Inputs | Backend | Tier | Gate |
|---|---|---|---|---|
| `render_page` | site, path, viewports[], full_page, selector, inject_css | Playwright (Hetzner) | R0 | none |
| `set_custom_css` | site, css, target (child theme or Additional CSS) | SSH / WP-CLI | R1 | snapshot + confirm |

Two parameters make this the whole game for styling:

- `viewports[]` checks desktop and mobile in the same call, and `selector` screenshots just the button or just the header instead of the whole page, keeping it fast.
- `inject_css` applies candidate CSS at render time, in the browser, without writing anything to the site. Claude can preview unlimited styling variations against the real live page and only commit the final approved version with `set_custom_css`.

Primary backend is Playwright on the Hetzner box: unattended, fleet-wide, serves both chat and automation. Claude in Chrome is an optional desktop adjunct for one-off interactive visual work, not the fleet engine.

---

## 5. Cross-cutting spine

Build these first. Everything else sits on them.

**Site registry (Supabase).** Maps slug to domain, wp path, SSH key reference, app password reference, and DA account. Secrets are referenced, not stored in plain text, and never returned to Claude.

**Gating middleware.** Implements the R1 confirm and the R2 plan/apply flow generically. Plans are rows in Supabase carrying the computed diff, the pre-flight backup id, a TTL, and a used flag.

**Audit log.** Records every call, reads included, with site, tool, input hash, plan id, result, and timestamp. This is the Law 25 paper trail and the "what did Claude change on Boucherie Beirut last Tuesday" lookup.

---

## 6. Styling loop: see, change, see again

Example request: "Make the hero button on jeconduis.com bigger and use our brand blue, and make sure it still looks right on mobile."

1. `render_page` on the homepage, desktop and mobile, scoped to the hero. Claude sees the current button on both.
2. Claude writes candidate CSS and calls `render_page` with `inject_css`. Nothing is written to the site. Claude sees the new button at both widths.
3. On mobile the button runs too wide. Claude adjusts and re-renders. Still just a preview. Now it looks right on both.
4. `set_custom_css` snapshots the stylesheet and writes the approved CSS into the child theme. One gated confirm.
5. `flush_cache`, then a final `render_page` against the live committed page to verify the real result matches the preview.

Step 5 is not redundant. The committed CSS has to win the specificity fight against the builder's inline styles on the real page and survive LiteSpeed cache. The final live render catches the classic failure where CSS looked perfect in preview but the builder overrode it on the actual site. If it does not match, Claude bumps specificity rather than leaving a silent miss.

### Realistic verdict on styling and UI

- **Strong:** CSS-level work. Colors, fonts, spacing, sizing, hover states, borders, shadows, responsive tweaks, show/hide, brand matching. Written into a child theme stylesheet, update-safe and reversible. Covers most of what the agency gets asked to change day to day. With the render loop, this is iterative and reliable.
- **Fiddly:** Page-builder and theme-options-controlled design. Column widths, per-element padding, the builder's own color pickers, header layout in the theme panel. Reachable but builder-specific and delicate. The safer move is usually to leave the structure alone and override appearance with CSS on top.
- **Supervised:** Deep structural redesign inside the visual builders. Possible but watched closely, not a confident one-shot.

The deciding factor is whether Claude can see the result. The render tool is what moves UI work from "wrote plausible CSS" to "made it look right," which is why it is first-class, not optional.

---

## 7. Build order

Blast radius grows only as confidence does.

1. **Spine plus R0 reads, including `render_page`.** Registry, secret resolution, audit log, and the read tools (`find_content`, `get_content`, `db_select`, `read_file`, `render_page`). Immediately useful, near-zero risk.
2. **R1 content writes plus `set_custom_css`.** Covers most daily agency work and unlocks the full styling loop early.
3. **`search_replace` and `set_option`** with plan/apply and backup. Unlocks serialization-safe bulk edits.
4. **Theme file `write_file` and `patch_file`.**
5. **Plugin and theme lifecycle.**
6. **DirectAdmin hosting tools.** Last, widest blast radius.

---

## 8. Open decisions

1. **Deployment posture.** Confirmed: direct to production with gated writes and mandatory pre-flight backups. Revisit only if a class of change proves too risky for prod even when gated, in which case add a staging-clone path using the DirectAdmin backup tooling.
2. **Registry seeding.** Seed from a CSV of the 40 sites, or build an `add_site` admin tool, or both.
3. **REST backend.** Use the official `mcp-adapter` plugin as the content backend, or implement REST calls directly in the server.

---

## 9. Stack summary

| Concern | Choice |
|---|---|
| Transport | MCP server |
| Server framework | FastAPI (Python) |
| Registry, plans, audit | Supabase |
| Execution | REST (app passwords), WP-CLI over SSH, DirectAdmin API |
| Rendering | Playwright on Hetzner |
| Client | Claude Desktop or Claude Code |
| Optional automation | Anthropic Messages API app over the same tool layer (Option D) |
