from datetime import timedelta

from wpctl.models import (
    AuditEntry,
    BackupTier,
    Plan,
    PlanStatus,
    Site,
    Tier,
    utcnow,
)
from wpctl.store.sqlite_store import SQLiteStore


def make_store(tmp_path):
    return SQLiteStore(str(tmp_path / "t.sqlite"))


def test_site_roundtrip_and_secret_refs_only(tmp_path):
    s = make_store(tmp_path)
    s.upsert_site(Site(slug="acme", domain="acme.com", wp_path="/var/www",
                       ssh_key_ref="ACME_KEY", app_password_ref="ACME_PW"))
    got = s.get_site("acme")
    assert got.domain == "acme.com"
    assert got.ssh_key_ref == "ACME_KEY"  # ref stored, resolved elsewhere
    assert [x.slug for x in s.list_sites()] == ["acme"]
    assert s.list_sites("acme") and not s.list_sites("zzz")


def test_plan_roundtrip(tmp_path):
    s = make_store(tmp_path)
    s.upsert_site(Site(slug="acme", domain="a.com", wp_path="/w"))
    p = Plan(id="ab12", site="acme", tool="search_replace", tier=Tier.R2,
             params={"search": "x"}, ttl_expires_at=utcnow() + timedelta(minutes=5),
             backup_tier=BackupTier.DB, target_hash="h1", diff_text="3 rows")
    s.create_plan(p)
    g = s.get_plan("ab12")
    assert g.tier == Tier.R2 and g.backup_tier == BackupTier.DB
    assert g.params == {"search": "x"} and g.target_hash == "h1"
    g.status = PlanStatus.APPLIED
    g.used = True
    s.update_plan(g)
    assert s.get_plan("ab12").status == PlanStatus.APPLIED


def test_site_lock_is_exclusive(tmp_path):
    s = make_store(tmp_path)
    s.upsert_site(Site(slug="acme", domain="a.com", wp_path="/w"))
    assert s.try_acquire_lock("acme", "plan1") is True
    assert s.try_acquire_lock("acme", "plan2") is False
    s.release_lock("acme", "plan1")
    assert s.try_acquire_lock("acme", "plan2") is True


def test_audit_records(tmp_path):
    s = make_store(tmp_path)
    s.record_audit(AuditEntry(site="acme", tool="list_sites", tier=Tier.R0,
                              input_hash="h", outcome="ok"))
    rows = s.recent_audit("acme")
    assert rows[0].tool == "list_sites" and rows[0].outcome == "ok"
