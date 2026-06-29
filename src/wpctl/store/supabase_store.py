"""Supabase store (production). Thin wrapper over the supabase-py client.

Schema lives in migrations/0001_init.sql. Apply migrations before use.
The supabase dependency is optional and imported lazily.
"""

from __future__ import annotations

import json
from datetime import datetime

from ..models import (
    AuditEntry,
    BackupTier,
    Plan,
    PlanStatus,
    Site,
    Tier,
)


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class SupabaseStore:
    def __init__(self, url: str, key: str) -> None:
        try:
            from supabase import create_client
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install 'wpctl[supabase]' to use WPCTL_STORE=supabase") from e
        self._c = create_client(url, key)

    # --- registry ---
    @staticmethod
    def _to_site(r: dict) -> Site:
        return Site(
            slug=r["slug"], domain=r["domain"], wp_path=r["wp_path"],
            ssh_host=r.get("ssh_host"), ssh_user=r.get("ssh_user"),
            ssh_port=r.get("ssh_port", 22), ssh_key_ref=r.get("ssh_key_ref"),
            rest_base=r.get("rest_base"), app_password_ref=r.get("app_password_ref"),
            app_user=r.get("app_user"), da_host=r.get("da_host"),
            da_account=r.get("da_account"), dns_provider=r.get("dns_provider", "directadmin"),
            active=r.get("active", True), notes=r.get("notes"),
        )

    def list_sites(self, filter: str | None = None) -> list[Site]:
        res = self._c.table("sites").select("*").order("slug").execute()
        sites = [self._to_site(r) for r in res.data]
        if filter:
            f = filter.lower()
            sites = [s for s in sites if f in s.slug.lower() or f in s.domain.lower()
                     or (s.notes and f in s.notes.lower())]
        return sites

    def get_site(self, slug: str) -> Site | None:
        res = self._c.table("sites").select("*").eq("slug", slug).limit(1).execute()
        return self._to_site(res.data[0]) if res.data else None

    def upsert_site(self, s: Site) -> None:
        self._c.table("sites").upsert({
            "slug": s.slug, "domain": s.domain, "wp_path": s.wp_path,
            "ssh_host": s.ssh_host, "ssh_user": s.ssh_user, "ssh_port": s.ssh_port,
            "ssh_key_ref": s.ssh_key_ref, "rest_base": s.rest_base,
            "app_password_ref": s.app_password_ref, "app_user": s.app_user,
            "da_host": s.da_host, "da_account": s.da_account,
            "dns_provider": s.dns_provider, "active": s.active, "notes": s.notes,
        }).execute()

    # --- plans ---
    def create_plan(self, p: Plan) -> None:
        self._c.table("plans").insert(self._plan_row(p)).execute()

    @staticmethod
    def _plan_row(p: Plan) -> dict:
        return {
            "id": p.id, "site": p.site, "tool": p.tool, "tier": p.tier.value,
            "params_json": p.params, "diff_text": p.diff_text, "target_hash": p.target_hash,
            "backup_tier": p.backup_tier.value, "preflight_backup_ref": p.preflight_backup_ref,
            "snapshot_ref": p.snapshot_ref, "status": p.status.value,
            "approved_by": p.approved_by, "ttl_expires_at": p.ttl_expires_at.isoformat(),
            "used": p.used, "result_json": p.result,
            "created_at": p.created_at.isoformat(),
            "applied_at": p.applied_at.isoformat() if p.applied_at else None,
        }

    @staticmethod
    def _to_plan(r: dict) -> Plan:
        params = r["params_json"]
        if isinstance(params, str):
            params = json.loads(params)
        result = r.get("result_json")
        if isinstance(result, str):
            result = json.loads(result)
        return Plan(
            id=r["id"], site=r["site"], tool=r["tool"], tier=Tier(r["tier"]),
            params=params, diff_text=r.get("diff_text"), target_hash=r.get("target_hash"),
            backup_tier=BackupTier(r.get("backup_tier", "none")),
            preflight_backup_ref=r.get("preflight_backup_ref"),
            snapshot_ref=r.get("snapshot_ref"), status=PlanStatus(r["status"]),
            approved_by=r.get("approved_by"), ttl_expires_at=_dt(r["ttl_expires_at"]),
            used=r.get("used", False), result=result,
            created_at=_dt(r["created_at"]), applied_at=_dt(r.get("applied_at")),
        )

    def get_plan(self, plan_id: str) -> Plan | None:
        res = self._c.table("plans").select("*").eq("id", plan_id).limit(1).execute()
        return self._to_plan(res.data[0]) if res.data else None

    def update_plan(self, p: Plan) -> None:
        self._c.table("plans").update(self._plan_row(p)).eq("id", p.id).execute()

    # --- lock ---
    def try_acquire_lock(self, site: str, holder: str) -> bool:
        try:
            self._c.table("site_locks").insert({"site": site, "holder": holder}).execute()
            return True
        except Exception:
            return False

    def release_lock(self, site: str, holder: str) -> None:
        self._c.table("site_locks").delete().eq("site", site).eq("holder", holder).execute()

    # --- audit ---
    def record_audit(self, e: AuditEntry) -> None:
        self._c.table("audit_log").insert({
            "ts": e.ts.isoformat(), "site": e.site, "tool": e.tool, "tier": e.tier.value,
            "input_hash": e.input_hash, "plan_id": e.plan_id, "actor": e.actor,
            "outcome": e.outcome, "result_summary": e.result_summary,
        }).execute()

    def recent_audit(self, site: str | None = None, limit: int = 50) -> list[AuditEntry]:
        q = self._c.table("audit_log").select("*").order("ts", desc=True).limit(limit)
        if site:
            q = q.eq("site", site)
        res = q.execute()
        return [
            AuditEntry(
                site=r.get("site"), tool=r["tool"], tier=Tier(r["tier"]),
                input_hash=r["input_hash"], outcome=r["outcome"], plan_id=r.get("plan_id"),
                actor=r.get("actor", "claude"), result_summary=r.get("result_summary"),
                ts=_dt(r["ts"]),
            )
            for r in res.data
        ]
