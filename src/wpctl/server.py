"""MCP server entry point.

Registers the R0 read tools plus the generic gating tools (apply_plan,
reject_plan, audit_tail). Write tools (R1/R2) register their planners/appliers
with ctx.gate in later build steps and are exposed as plan_* tools here.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .context import AppContext
from .gating import GateError
from .tools import content, files, options, registry

ctx = AppContext.build()
mcp = FastMCP("wpctl")


# --- Registry / resolution (R0) ---
@mcp.tool()
async def list_sites(filter: str | None = None) -> dict[str, Any]:
    """List fleet sites by friendly slug. Optional substring filter on slug/domain/notes."""
    return await registry.list_sites(ctx, filter)


@mcp.tool()
async def get_site(site: str) -> dict[str, Any]:
    """Get one site's public info plus a live REST health ping."""
    return await registry.get_site(ctx, site)


@mcp.tool()
async def capabilities(site: str) -> dict[str, Any]:
    """Report REST namespaces available on a site (AIOSEO, WooCommerce, ...)."""
    return await registry.capabilities(ctx, site)


# --- Content (R0) ---
@mcp.tool()
async def find_content(site: str, query: str = "", type: str = "posts",
                       status: str = "any") -> dict[str, Any]:
    """Search a site's content (posts/pages/CPTs) via REST."""
    return await content.find_content(ctx, site, query, type, status)


@mcp.tool()
async def get_content(site: str, id: int, type: str = "posts") -> dict[str, Any]:
    """Fetch one content item's raw title/body by id."""
    return await content.get_content(ctx, site, id, type)


# --- Options / DB-safe (R0) ---
@mcp.tool()
async def get_option(site: str, key: str) -> dict[str, Any]:
    """Read a wp_options value via WP-CLI."""
    return await options.get_option(ctx, site, key)


@mcp.tool()
async def db_select(site: str, sql: str) -> dict[str, Any]:
    """Run a read-only SQL query (SELECT/SHOW/DESCRIBE only; guarded)."""
    return await options.db_select(ctx, site, sql)


# --- Files (R0, jailed to wp-content) ---
@mcp.tool()
async def list_files(site: str, path: str = "") -> dict[str, Any]:
    """List files under the site's wp-content (path-jailed)."""
    return await files.list_files(ctx, site, path)


@mcp.tool()
async def read_file(site: str, path: str) -> dict[str, Any]:
    """Read a file under the site's wp-content (path-jailed)."""
    return await files.read_file(ctx, site, path)


# --- Generic gating surface (used by all R1/R2 tools) ---
@mcp.tool()
async def apply_plan(plan_id: str, confirm_token: str | None = None) -> dict[str, Any]:
    """Execute a previously created plan after operator approval. For the
    chat_token approver, pass the confirm_token the operator relayed."""
    try:
        return await ctx.gate.apply_plan(plan_id, confirm_token)
    except GateError as e:
        return {"error": str(e)}


@mcp.tool()
async def reject_plan(plan_id: str) -> dict[str, Any]:
    """Reject/cancel a pending plan."""
    try:
        return ctx.gate.reject_plan(plan_id)
    except GateError as e:
        return {"error": str(e)}


@mcp.tool()
async def audit_tail(site: str | None = None, limit: int = 30) -> dict[str, Any]:
    """Recent audit entries, optionally filtered by site."""
    entries = ctx.store.recent_audit(site, limit)
    return {"entries": [
        {"ts": e.ts.isoformat(), "site": e.site, "tool": e.tool, "tier": e.tier.value,
         "outcome": e.outcome, "plan_id": e.plan_id, "summary": e.result_summary}
        for e in entries
    ]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
