"""Theme/file read tools (R0, SSH). Path-jailed to the site's wp-content."""

from __future__ import annotations

import posixpath
from typing import Any

from ..context import AppContext
from ..models import Site, Tier


def _require(ctx: AppContext, site: str) -> Site:
    s = ctx.store.get_site(site)
    if s is None:
        raise ValueError(f"unknown site slug: {site!r}")
    return s


def jail_path(site: Site, path: str) -> str:
    """Resolve `path` (relative to wp-content) and ensure it stays inside it.
    Prevents touching wp-config or escaping the docroot."""
    root = posixpath.normpath(posixpath.join(site.wp_path, "wp-content"))
    candidate = posixpath.normpath(posixpath.join(root, path.lstrip("/")))
    if candidate != root and not candidate.startswith(root + "/"):
        raise ValueError(f"path escapes wp-content jail: {path!r}")
    return candidate


async def list_files(ctx: AppContext, site: str, path: str = "") -> dict[str, Any]:
    s = _require(ctx, site)
    target = jail_path(s, path)
    try:
        res = ctx.ssh.run(s, ["ls", "-la", "--", target])
    except Exception as e:
        ctx.gate.audit(site, "list_files", Tier.R0, {"path": path}, "error", str(e))
        raise
    if res.code != 0:
        raise ValueError(res.stderr.strip() or f"cannot list {path!r}")
    entries = [line for line in res.stdout.splitlines() if line.strip()]
    ctx.gate.audit(site, "list_files", Tier.R0, {"path": path}, "ok", f"{len(entries)} entries")
    return {"path": target, "entries": entries}


async def read_file(ctx: AppContext, site: str, path: str) -> dict[str, Any]:
    s = _require(ctx, site)
    target = jail_path(s, path)
    try:
        res = ctx.ssh.run(s, ["cat", "--", target])
    except Exception as e:
        ctx.gate.audit(site, "read_file", Tier.R0, {"path": path}, "error", str(e))
        raise
    if res.code != 0:
        raise ValueError(res.stderr.strip() or f"cannot read {path!r}")
    ctx.gate.audit(site, "read_file", Tier.R0, {"path": path}, "ok",
                   f"{len(res.stdout)} bytes")
    return {"path": target, "content": res.stdout}
