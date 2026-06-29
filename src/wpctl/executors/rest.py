"""WordPress REST API client (Application Password auth).

For R0 reads we call wp-json directly — no per-site mcp-adapter plugin needed.
Credentials are resolved server-side and never surfaced to Claude.
"""

from __future__ import annotations

from typing import Any

from ..models import Site
from ..secrets import SecretResolver


class RestClient:
    def __init__(self, secrets: SecretResolver) -> None:
        self._secrets = secrets

    def _auth(self, site: Site) -> tuple[str, str] | None:
        if site.app_user and site.app_password_ref:
            return (site.app_user, self._secrets.resolve(site.app_password_ref))
        return None

    async def get(self, site: Site, path: str, params: dict[str, Any] | None = None) -> Any:
        import httpx

        url = f"{site.resolved_rest_base.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url, params=params, auth=self._auth(site))
            r.raise_for_status()
            return r.json()

    async def health(self, site: Site) -> dict[str, Any]:
        """Lightweight liveness ping used by get_site."""
        import httpx

        url = f"{site.resolved_rest_base.rstrip('/')}/"
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
                r = await c.get(url)
                return {"reachable": r.status_code < 500, "status": r.status_code}
        except httpx.HTTPError as e:
            return {"reachable": False, "error": str(e)}
