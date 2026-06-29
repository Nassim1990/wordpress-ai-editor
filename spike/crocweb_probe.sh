#!/usr/bin/env bash
# crocweb_probe.sh — feasibility spike for the WordPress Control Server.
#
# Validates, READ-ONLY, whether one CrocWeb / DirectAdmin account can support the
# WP-CLI-over-SSH "workhorse" backend and the DirectAdmin API before any write
# tools are built (gap-analysis items #10, #11, #13). It changes nothing.
#
# Usage:
#   spike/crocweb_probe.sh \
#     --ssh user@host [--port 22] [--key ~/.ssh/id_rsa] \
#     --wp-path /home/croc/domains/example.com/public_html \
#     [--da-host https://server.crocweb.com:2222] [--da-user reseller]
#
# DA password is read from $DA_PASSWORD if set (never pass it on the CLI).
set -uo pipefail

SSH_TARGET="" PORT=22 KEY="" WP_PATH="" DA_HOST="" DA_USER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --ssh) SSH_TARGET="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --key) KEY="$2"; shift 2;;
    --wp-path) WP_PATH="$2"; shift 2;;
    --da-host) DA_HOST="$2"; shift 2;;
    --da-user) DA_USER="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -n "$SSH_TARGET" ] || { echo "--ssh user@host is required" >&2; exit 2; }

SSH_OPTS=(-p "$PORT" -o ConnectTimeout=15 -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")

pass=0 fail=0 warn=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no()   { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
warnx(){ printf '  \033[33mWARN\033[0m %s\n' "$1"; warn=$((warn+1)); }

# Run a command on the remote host; prints nothing, returns its exit code.
rsh() { ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$@" 2>/dev/null; }

echo "== 1. SSH connectivity & shell =="
if out=$(rsh 'echo wpctl-ok'); [ "$out" = "wpctl-ok" ]; then
  ok "SSH login + interactive shell"
else
  no "cannot get a shell over SSH (key not authorized, IP not allowlisted, or shell disabled)"
  echo; echo "SSH is the foundation of the WP-CLI backend. Stopping."; exit 1
fi

echo "== 2. WP-CLI availability =="
if ver=$(rsh 'wp --version --allow-root' 2>/dev/null) && [ -n "$ver" ]; then
  ok "wp-cli present: $ver"
  WP="wp"
elif ver=$(rsh 'php $HOME/wp-cli.phar --version' 2>/dev/null) && [ -n "$ver" ]; then
  warnx "wp-cli only as wp-cli.phar (no global 'wp'): $ver — set executor to use the phar"
  WP="php \$HOME/wp-cli.phar"
else
  no "wp-cli not found (no 'wp' and no wp-cli.phar). The WP-CLI backend cannot run."
  WP=""
fi

if [ -n "$WP" ] && [ -n "$WP_PATH" ]; then
  echo "== 3. WP-CLI against the install ($WP_PATH) =="
  if v=$(rsh "$WP core version --path='$WP_PATH' --allow-root" 2>/dev/null) && [ -n "$v" ]; then
    ok "core version: $v"
  else
    no "wp core version failed — wrong path, or wp-cli can't load WP"
  fi
  if rsh "$WP option get siteurl --path='$WP_PATH' --allow-root" >/dev/null 2>&1; then
    ok "wp option get (reads wp_options)"
  else
    no "wp option get failed"
  fi
  echo "== 4. Raw DB access (needed by db_select / search-replace) =="
  if rsh "$WP db query 'SELECT 1' --path='$WP_PATH' --allow-root" >/dev/null 2>&1; then
    ok "wp db query (raw SQL) allowed"
  else
    no "wp db query blocked — db_select and the diff for search_replace won't work"
  fi
  if rsh "$WP search-replace 'https://__nomatch__' 'https://__nomatch__' --dry-run --path='$WP_PATH' --allow-root" >/dev/null 2>&1; then
    ok "wp search-replace --dry-run works (serialization-safe bulk edits feasible)"
  else
    warnx "wp search-replace --dry-run failed — investigate before building search_replace"
  fi
elif [ -z "$WP_PATH" ]; then
  warnx "skipping install checks: pass --wp-path to test against the real WordPress"
fi

echo "== 5. wp-content writability (write tools land here) =="
if perm=$(rsh "test -w '$WP_PATH/wp-content' && echo writable || echo readonly" 2>/dev/null); then
  [ "$perm" = "writable" ] && ok "wp-content is writable by the SSH user" \
                           || warnx "wp-content not writable by this user — write_file/set_custom_css need it"
fi

echo "== 6. DirectAdmin API scope =="
if [ -n "$DA_HOST" ] && [ -n "$DA_USER" ]; then
  if [ -z "${DA_PASSWORD:-}" ]; then
    warnx "DA_PASSWORD not set in env — skipping DA API probe"
  else
    # CMD_API_SHOW_DOMAINS is the cheapest read-only DA endpoint.
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
      -u "$DA_USER:$DA_PASSWORD" "$DA_HOST/CMD_API_SHOW_DOMAINS")
    if [ "$code" = "200" ]; then
      ok "DA API reachable + authenticated (CMD_API_SHOW_DOMAINS 200)"
      # Backup endpoint presence governs the pre-flight backup engine.
      bcode=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        -u "$DA_USER:$DA_PASSWORD" "$DA_HOST/CMD_API_SITE_BACKUP")
      [ "$bcode" = "200" ] && ok "CMD_API_SITE_BACKUP reachable (pre-flight backups feasible)" \
                           || warnx "CMD_API_SITE_BACKUP returned $bcode — confirm backup API on this plan"
    else
      no "DA API auth/reach failed (HTTP $code) — hosting tools (#11) may need admin-level access"
    fi
  fi
else
  warnx "skipping DA API checks: pass --da-host and --da-user (and export DA_PASSWORD)"
fi

echo
echo "== Summary: $pass pass, $warn warn, $fail fail =="
[ "$fail" -eq 0 ] && echo "Workhorse backend looks feasible on this account." \
                  || echo "Blocking gaps found — resolve before building write tools."
exit "$fail"
