"""Registry / resolution tools (R0)."""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..models import Site, Tier

# Fields that are safe to surface to Claude. Secret *refs* are deliberately
# excluded — Claude addresses sites by slug and never sees credentials.
_PUBLIC_FIELDS = ("slug", "domain", "wp_path", "dns_provider", "active", "notes")


def _public_site(s: Site) -> dict[str, Any]:
    d = {f: getattr(s, f) for f in _PUBLIC_FIELDS}
    d["has_ssh"] = bool(s.ssh_host and s.ssh_key_ref)
    d["has_rest"] = bool(s.app_user and s.app_password_ref)
    d["has_da"] = bool(s.da_host and s.da_account)
    return d


async def list_sites(ctx: AppContext, filter: str | None = None) -> dict[str, Any]:
    sites = ctx.store.list_sites(filter)
    ctx.gate.audit(None, "list_sites", Tier.R0, {"filter": filter}, "ok",
                   f"{len(sites)} sites")
    return {"sites": [_public_site(s) for s in sites]}


async def get_site(ctx: AppContext, site: str) -> dict[str, Any]:
    s = ctx.store.get_site(site)
    if s is None:
        ctx.gate.audit(site, "get_site", Tier.R0, {"site": site}, "error", "unknown site")
        raise ValueError(f"unknown site slug: {site!r}")
    info = _public_site(s)
    info["health"] = await ctx.rest.health(s)
    ctx.gate.audit(site, "get_site", Tier.R0, {"site": site}, "ok")
    return info


async def capabilities(ctx: AppContext, site: str) -> dict[str, Any]:
    s = ctx.store.get_site(site)
    if s is None:
        raise ValueError(f"unknown site slug: {site!r}")
    # REST root advertises namespaces (e.g. aioseo, wp/v2). Degrade gracefully.
    try:
        root = await ctx.rest.get(s, "/")
        namespaces = root.get("namespaces", []) if isinstance(root, dict) else []
    except Exception as e:
        ctx.gate.audit(site, "capabilities", Tier.R0, {"site": site}, "error", str(e))
        return {"site": site, "reachable": False, "error": str(e)}
    ctx.gate.audit(site, "capabilities", Tier.R0, {"site": site}, "ok")
    return {
        "site": site,
        "namespaces": namespaces,
        "has_aioseo": any("aioseo" in n for n in namespaces),
        "has_woocommerce": any("wc/" in n for n in namespaces),
    }
