"""SQLite store — runnable locally with no external services.

Mirrors migrations/0001_init.sql. Used for dev and the test suite.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from ..models import (
    AuditEntry,
    BackupTier,
    Plan,
    PlanStatus,
    Site,
    Tier,
)

_SCHEMA = """
create table if not exists sites (
    slug text primary key, domain text not null, wp_path text not null,
    ssh_host text, ssh_user text, ssh_port integer not null default 22,
    ssh_key_ref text, rest_base text, app_password_ref text, app_user text,
    da_host text, da_account text, dns_provider text not null default 'directadmin',
    active integer not null default 1, notes text,
    created_at text not null default (datetime('now'))
);
create table if not exists plans (
    id text primary key, site text not null, tool text not null, tier text not null,
    params_json text not null, diff_text text, target_hash text,
    backup_tier text not null default 'none', preflight_backup_ref text,
    snapshot_ref text, status text not null default 'pending', approved_by text,
    ttl_expires_at text not null, used integer not null default 0,
    result_json text, created_at text not null, applied_at text
);
create table if not exists site_locks (
    site text primary key, holder text not null,
    acquired_at text not null default (datetime('now'))
);
create table if not exists audit_log (
    id integer primary key autoincrement, ts text not null,
    site text, tool text not null, tier text not null, input_hash text not null,
    plan_id text, actor text not null default 'claude', outcome text not null,
    result_summary text
);
"""


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


class SQLiteStore:
    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # --- registry ---
    def _row_to_site(self, r: sqlite3.Row) -> Site:
        return Site(
            slug=r["slug"], domain=r["domain"], wp_path=r["wp_path"],
            ssh_host=r["ssh_host"], ssh_user=r["ssh_user"], ssh_port=r["ssh_port"],
            ssh_key_ref=r["ssh_key_ref"], rest_base=r["rest_base"],
            app_password_ref=r["app_password_ref"], app_user=r["app_user"],
            da_host=r["da_host"], da_account=r["da_account"],
            dns_provider=r["dns_provider"], active=bool(r["active"]), notes=r["notes"],
        )

    def list_sites(self, filter: str | None = None) -> list[Site]:
        with self._lock:
            rows = self._conn.execute("select * from sites order by slug").fetchall()
        sites = [self._row_to_site(r) for r in rows]
        if filter:
            f = filter.lower()
            sites = [s for s in sites if f in s.slug.lower() or f in s.domain.lower()
                     or (s.notes and f in s.notes.lower())]
        return sites

    def get_site(self, slug: str) -> Site | None:
        with self._lock:
            r = self._conn.execute("select * from sites where slug=?", (slug,)).fetchone()
        return self._row_to_site(r) if r else None

    def upsert_site(self, s: Site) -> None:
        with self._lock:
            self._conn.execute(
                """insert into sites
                (slug,domain,wp_path,ssh_host,ssh_user,ssh_port,ssh_key_ref,rest_base,
                 app_password_ref,app_user,da_host,da_account,dns_provider,active,notes)
                values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(slug) do update set
                domain=excluded.domain, wp_path=excluded.wp_path, ssh_host=excluded.ssh_host,
                ssh_user=excluded.ssh_user, ssh_port=excluded.ssh_port,
                ssh_key_ref=excluded.ssh_key_ref, rest_base=excluded.rest_base,
                app_password_ref=excluded.app_password_ref, app_user=excluded.app_user,
                da_host=excluded.da_host, da_account=excluded.da_account,
                dns_provider=excluded.dns_provider, active=excluded.active, notes=excluded.notes""",
                (s.slug, s.domain, s.wp_path, s.ssh_host, s.ssh_user, s.ssh_port,
                 s.ssh_key_ref, s.rest_base, s.app_password_ref, s.app_user,
                 s.da_host, s.da_account, s.dns_provider, int(s.active), s.notes),
            )
            self._conn.commit()

    # --- plans ---
    def create_plan(self, p: Plan) -> None:
        with self._lock:
            self._conn.execute(
                """insert into plans
                (id,site,tool,tier,params_json,diff_text,target_hash,backup_tier,
                 preflight_backup_ref,snapshot_ref,status,approved_by,ttl_expires_at,
                 used,result_json,created_at,applied_at)
                values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (p.id, p.site, p.tool, p.tier.value, json.dumps(p.params), p.diff_text,
                 p.target_hash, p.backup_tier.value, p.preflight_backup_ref, p.snapshot_ref,
                 p.status.value, p.approved_by, p.ttl_expires_at.isoformat(), int(p.used),
                 json.dumps(p.result) if p.result is not None else None,
                 p.created_at.isoformat(), p.applied_at.isoformat() if p.applied_at else None),
            )
            self._conn.commit()

    def _row_to_plan(self, r: sqlite3.Row) -> Plan:
        return Plan(
            id=r["id"], site=r["site"], tool=r["tool"], tier=Tier(r["tier"]),
            params=json.loads(r["params_json"]), diff_text=r["diff_text"],
            target_hash=r["target_hash"], backup_tier=BackupTier(r["backup_tier"]),
            preflight_backup_ref=r["preflight_backup_ref"], snapshot_ref=r["snapshot_ref"],
            status=PlanStatus(r["status"]), approved_by=r["approved_by"],
            ttl_expires_at=_dt(r["ttl_expires_at"]), used=bool(r["used"]),
            result=json.loads(r["result_json"]) if r["result_json"] else None,
            created_at=_dt(r["created_at"]), applied_at=_dt(r["applied_at"]),
        )

    def get_plan(self, plan_id: str) -> Plan | None:
        with self._lock:
            r = self._conn.execute("select * from plans where id=?", (plan_id,)).fetchone()
        return self._row_to_plan(r) if r else None

    def update_plan(self, p: Plan) -> None:
        with self._lock:
            self._conn.execute(
                """update plans set status=?, approved_by=?, used=?, result_json=?,
                   preflight_backup_ref=?, snapshot_ref=?, diff_text=?, target_hash=?,
                   applied_at=? where id=?""",
                (p.status.value, p.approved_by, int(p.used),
                 json.dumps(p.result) if p.result is not None else None,
                 p.preflight_backup_ref, p.snapshot_ref, p.diff_text, p.target_hash,
                 p.applied_at.isoformat() if p.applied_at else None, p.id),
            )
            self._conn.commit()

    # --- lock ---
    def try_acquire_lock(self, site: str, holder: str) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    "insert into site_locks(site,holder) values(?,?)", (site, holder)
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def release_lock(self, site: str, holder: str) -> None:
        with self._lock:
            self._conn.execute(
                "delete from site_locks where site=? and holder=?", (site, holder)
            )
            self._conn.commit()

    # --- audit ---
    def record_audit(self, e: AuditEntry) -> None:
        with self._lock:
            self._conn.execute(
                """insert into audit_log
                (ts,site,tool,tier,input_hash,plan_id,actor,outcome,result_summary)
                values (?,?,?,?,?,?,?,?,?)""",
                (e.ts.isoformat(), e.site, e.tool, e.tier.value, e.input_hash,
                 e.plan_id, e.actor, e.outcome, e.result_summary),
            )
            self._conn.commit()

    def recent_audit(self, site: str | None = None, limit: int = 50) -> list[AuditEntry]:
        with self._lock:
            if site:
                rows = self._conn.execute(
                    "select * from audit_log where site=? order by ts desc limit ?",
                    (site, limit)).fetchall()
            else:
                rows = self._conn.execute(
                    "select * from audit_log order by ts desc limit ?", (limit,)).fetchall()
        return [
            AuditEntry(
                site=r["site"], tool=r["tool"], tier=Tier(r["tier"]),
                input_hash=r["input_hash"], outcome=r["outcome"], plan_id=r["plan_id"],
                actor=r["actor"], result_summary=r["result_summary"],
                ts=datetime.fromisoformat(r["ts"]).replace(tzinfo=timezone.utc)
                if "+" not in r["ts"] else datetime.fromisoformat(r["ts"]),
            )
            for r in rows
        ]
