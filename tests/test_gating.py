"""Exercise the full plan -> approve -> apply flow and every gate refusal."""

import pytest

from wpctl.config import Config
from wpctl.gating import GateError
from wpctl.gating.approver import AutoApprover, ChatTokenApprover, confirm_token
from wpctl.gating.middleware import Gate
from wpctl.models import BackupTier, PlanStatus, Site, Tier
from wpctl.store.sqlite_store import SQLiteStore


def base_cfg(**kw):
    defaults = dict(store="sqlite", sqlite_path=":memory:", supabase_url=None,
                    supabase_key=None, approver="chat_token",
                    plan_ttl_seconds=900, secrets="env")
    defaults.update(kw)
    return Config(**defaults)


def setup_gate(tmp_path, approver, ttl=900):
    store = SQLiteStore(str(tmp_path / "g.sqlite"))
    store.upsert_site(Site(slug="acme", domain="a.com", wp_path="/w"))
    gate = Gate(store, approver, base_cfg(plan_ttl_seconds=ttl))
    return store, gate


def register_counting_write(gate, tier=Tier.R2, backup=BackupTier.DB, hash_box=None):
    """A fake write whose target hash comes from a mutable box so we can simulate drift."""
    hash_box = hash_box if hash_box is not None else {"h": "v1"}
    applied = {"n": 0}

    async def planner(site, params):
        return (f"would set {params.get('value')}", hash_box["h"])

    async def applier(site, params, plan):
        applied["n"] += 1
        return {"set": params.get("value")}

    gate.register_write("set_thing", tier, backup, planner, applier)
    return hash_box, applied


@pytest.mark.asyncio
async def test_chat_token_happy_path(tmp_path):
    store, gate = setup_gate(tmp_path, ChatTokenApprover())
    _, applied = register_counting_write(gate)

    planned = await gate.plan("set_thing", "acme", {"value": "blue"})
    assert planned["tier"] == "R2"
    assert "confirm_token" in planned
    pid = planned["plan_id"]

    res = await gate.apply_plan(pid, planned["confirm_token"])
    assert res["status"] == "applied"
    assert res["result"] == {"set": "blue"}
    assert res["backup_ref"]  # R2 took a pre-flight backup
    assert applied["n"] == 1
    assert store.get_plan(pid).status == PlanStatus.APPLIED


@pytest.mark.asyncio
async def test_bad_token_is_denied(tmp_path):
    _, gate = setup_gate(tmp_path, ChatTokenApprover())
    _, applied = register_counting_write(gate)
    planned = await gate.plan("set_thing", "acme", {"value": "x"})
    with pytest.raises(GateError, match="confirm_token"):
        await gate.apply_plan(planned["plan_id"], "APPLY-wrong")
    assert applied["n"] == 0  # nothing executed


@pytest.mark.asyncio
async def test_single_use(tmp_path):
    _, gate = setup_gate(tmp_path, ChatTokenApprover())
    register_counting_write(gate)
    planned = await gate.plan("set_thing", "acme", {"value": "x"})
    tok = planned["confirm_token"]
    await gate.apply_plan(planned["plan_id"], tok)
    with pytest.raises(GateError, match="already used"):
        await gate.apply_plan(planned["plan_id"], tok)


@pytest.mark.asyncio
async def test_expired_plan(tmp_path):
    _, gate = setup_gate(tmp_path, ChatTokenApprover(), ttl=-1)  # already expired
    register_counting_write(gate)
    planned = await gate.plan("set_thing", "acme", {"value": "x"})
    with pytest.raises(GateError, match="expired"):
        await gate.apply_plan(planned["plan_id"], planned["confirm_token"])


@pytest.mark.asyncio
async def test_drift_guard(tmp_path):
    _, gate = setup_gate(tmp_path, ChatTokenApprover())
    hash_box, applied = register_counting_write(gate)
    planned = await gate.plan("set_thing", "acme", {"value": "x"})
    hash_box["h"] = "v2"  # target changed out of band after planning
    with pytest.raises(GateError, match="changed since the plan"):
        await gate.apply_plan(planned["plan_id"], planned["confirm_token"])
    assert applied["n"] == 0


@pytest.mark.asyncio
async def test_rejected_plan_cannot_apply(tmp_path):
    _, gate = setup_gate(tmp_path, ChatTokenApprover())
    register_counting_write(gate)
    planned = await gate.plan("set_thing", "acme", {"value": "x"})
    gate.reject_plan(planned["plan_id"])
    with pytest.raises(GateError, match="rejected"):
        await gate.apply_plan(planned["plan_id"], planned["confirm_token"])


@pytest.mark.asyncio
async def test_r1_takes_no_backup(tmp_path):
    _, gate = setup_gate(tmp_path, AutoApprover())
    register_counting_write(gate, tier=Tier.R1, backup=BackupTier.NONE)
    planned = await gate.plan("set_thing", "acme", {"value": "x"})
    res = await gate.apply_plan(planned["plan_id"])  # auto approver, no token
    assert res["status"] == "applied"
    assert res["backup_ref"] is None  # R1 / none backup tier


@pytest.mark.asyncio
async def test_apply_failure_reports_backup_for_rollback(tmp_path):
    _, gate = setup_gate(tmp_path, AutoApprover())

    async def planner(site, params):
        return ("diff", "v1")

    async def applier(site, params, plan):
        raise RuntimeError("disk full")

    gate.register_write("boom", Tier.R2, BackupTier.ACCOUNT, planner, applier)
    planned = await gate.plan("boom", "acme", {})
    with pytest.raises(GateError, match="Restore from backup"):
        await gate.apply_plan(planned["plan_id"])


@pytest.mark.asyncio
async def test_unknown_site_and_tool(tmp_path):
    _, gate = setup_gate(tmp_path, ChatTokenApprover())
    register_counting_write(gate)
    with pytest.raises(GateError, match="unknown site"):
        await gate.plan("set_thing", "nope", {"value": "x"})
    with pytest.raises(GateError, match="not a registered write"):
        await gate.plan("ghost", "acme", {"value": "x"})


def test_confirm_token_is_deterministic_per_plan():
    from wpctl.models import Plan, utcnow
    from datetime import timedelta
    p = Plan(id="abc", site="s", tool="t", tier=Tier.R1, params={},
             ttl_expires_at=utcnow() + timedelta(minutes=1))
    assert confirm_token(p) == confirm_token(p)
    assert confirm_token(p).startswith("APPLY-abc-")
