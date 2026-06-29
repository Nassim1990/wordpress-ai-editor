"""Options and DB-safe read tools (R0, WP-CLI)."""

from __future__ import annotations

import re
from typing import Any

from ..context import AppContext
from ..models import Tier

# SELECT-only guard for db_select. Rejects anything that could mutate or chain.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
    r"into\s+outfile|load_data|set)\b",
    re.IGNORECASE,
)


def _require(ctx: AppContext, site: str):
    s = ctx.store.get_site(site)
    if s is None:
        raise ValueError(f"unknown site slug: {site!r}")
    return s


def assert_select_only(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("db_select runs a single statement; remove ';'")
    low = stripped.lower()
    if not (low.startswith("select") or low.startswith("show") or low.startswith("describe")):
        raise ValueError("db_select only allows SELECT / SHOW / DESCRIBE")
    if _FORBIDDEN.search(stripped):
        raise ValueError("db_select rejected: statement contains a write/DDL keyword")


async def get_option(ctx: AppContext, site: str, key: str) -> dict[str, Any]:
    s = _require(ctx, site)
    # value resolution runs WP-CLI over SSH; raises if SSH/WP-CLI unavailable.
    try:
        value = ctx.ssh.wp(s, ["option", "get", key, "--format=json"])
    except Exception as e:
        ctx.gate.audit(site, "get_option", Tier.R0, {"key": key}, "error", str(e))
        raise
    ctx.gate.audit(site, "get_option", Tier.R0, {"key": key}, "ok")
    return {"key": key, "value": value.strip()}


async def db_select(ctx: AppContext, site: str, sql: str) -> dict[str, Any]:
    s = _require(ctx, site)
    assert_select_only(sql)  # parser guard before anything touches the site
    try:
        out = ctx.ssh.wp(s, ["db", "query", sql, "--skip-column-names"])
    except Exception as e:
        ctx.gate.audit(site, "db_select", Tier.R0, {"sql_hash": True}, "error", str(e))
        raise
    rows = [line for line in out.splitlines() if line.strip()]
    ctx.gate.audit(site, "db_select", Tier.R0, {"sql_hash": True}, "ok", f"{len(rows)} rows")
    return {"rows": rows}
