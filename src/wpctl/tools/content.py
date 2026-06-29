"""Content read tools (R0, REST primary)."""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..models import Tier


def _require(ctx: AppContext, site: str):
    s = ctx.store.get_site(site)
    if s is None:
        raise ValueError(f"unknown site slug: {site!r}")
    return s


async def find_content(ctx: AppContext, site: str, query: str = "",
                       type: str = "posts", status: str = "any") -> dict[str, Any]:
    """Search content via REST. Note: REST search is title/excerpt-biased; full
    serialized/shortcode body search is a documented limitation handled by the
    WP-CLI db fallback in a later step."""
    s = _require(ctx, site)
    params: dict[str, Any] = {"per_page": 20}
    if query:
        params["search"] = query
    if status and status != "any":
        params["status"] = status
    try:
        items = await ctx.rest.get(s, f"/wp/v2/{type}", params)
    except Exception as e:
        ctx.gate.audit(site, "find_content", Tier.R0, params, "error", str(e))
        raise
    results = [
        {"id": it.get("id"), "title": (it.get("title") or {}).get("rendered"),
         "status": it.get("status"), "link": it.get("link")}
        for it in (items if isinstance(items, list) else [])
    ]
    ctx.gate.audit(site, "find_content", Tier.R0, params, "ok", f"{len(results)} hits")
    return {"results": results}


async def get_content(ctx: AppContext, site: str, id: int,
                      type: str = "posts") -> dict[str, Any]:
    s = _require(ctx, site)
    try:
        item = await ctx.rest.get(s, f"/wp/v2/{type}/{id}", {"context": "edit"})
    except Exception as e:
        ctx.gate.audit(site, "get_content", Tier.R0, {"id": id}, "error", str(e))
        raise
    ctx.gate.audit(site, "get_content", Tier.R0, {"id": id, "type": type}, "ok")
    return {
        "id": item.get("id"),
        "title": (item.get("title") or {}).get("raw") or (item.get("title") or {}).get("rendered"),
        "status": item.get("status"),
        "content": (item.get("content") or {}).get("raw") or (item.get("content") or {}).get("rendered"),
        "link": item.get("link"),
        "modified": item.get("modified"),
    }
