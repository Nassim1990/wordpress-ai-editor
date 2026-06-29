# Feasibility spike — CrocWeb / DirectAdmin

`crocweb_probe.sh` answers the question the spec assumes but never validates:
**can one CrocWeb reseller account actually run the WP-CLI-over-SSH backend and
the DirectAdmin API?** (Gap-analysis items #10, #11, #13.) Run it against **one**
account before building any write tools.

It is strictly **read-only** — it lists, queries `SELECT 1`, runs
`search-replace --dry-run`, and hits the cheapest DA read endpoints. It writes
nothing.

## Run

```bash
chmod +x spike/crocweb_probe.sh
export DA_PASSWORD='...'          # optional, for the DA API section
spike/crocweb_probe.sh \
  --ssh croc@server.crocweb.com --port 22 --key ~/.ssh/croc_id \
  --wp-path /home/croc/domains/boucheriebeirut.com/public_html \
  --da-host https://server.crocweb.com:2222 --da-user croc
```

## What each check decides

| Check | If it fails… |
|---|---|
| 1. SSH shell | The whole WP-CLI backend is off the table on this host. Confirm key is authorized and the server's IP is allowlisted (#13). Hard stop. |
| 2. wp-cli present | Need to ship/point at `wp-cli.phar`; executor must use the phar path. |
| 3. wp core / option | Wrong `wp_path`, or wp-cli can't bootstrap WP. |
| 4. raw db query | `db_select` and the row-count diff for `search_replace` won't work — re-scope those tools. |
| 5. wp-content writable | `write_file` / `set_custom_css` need write access as this user. |
| 6. DA API | Hosting tools (backups, DNS, SSL, provision) may require admin-level access, not reseller (#11). The backup endpoint specifically gates the R2 pre-flight backup engine. |

Exit code is the number of failed checks (0 = feasible). Capture the output and
drop it next to this file as `results-<account>.txt` so the decision is recorded.
