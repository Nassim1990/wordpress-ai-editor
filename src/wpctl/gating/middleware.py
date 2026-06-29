"""Gating middleware.

Enforces the R0/R1/R2 tiers generically so tools only *declare* a tier; they do
not each reimplement safety.

  R0  read       -> run, audit.
  R1  reversible -> plan (snapshot) -> approve -> apply.
  R2  destructive-> plan (dry-run/diff) -> approve -> pre-flight backup -> apply.

Both write tiers go through one plan->approve->apply flow. The differences are
data: R2 plans carry a non-`none` backup_tier and a computed diff; R1 plans take
a lightweight snapshot. Writes register a *planner* and an *applier* keyed by
tool name, so apply_plan can re-dispatch from a stored plan.
"""

from __future__ import annotations

import hashlib
import json
import secrets as _secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable

from ..config import Config
from ..models import (
    AuditEntry,
    BackupTier,
    Plan,
    PlanStatus,
    Site,
    Tier,
    utcnow,
)
from ..store.base import Store
from .approver import Approver, confirm_token

# planner(site, params) -> (diff_text, target_hash)
Planner = Callable[[Site, dict], Awaitable[tuple[str, str | None]]]
# applier(site, params, plan) -> result dict
Applier = Callable[[Site, dict, Plan], Awaitable[dict]]


class GateError(Exception):
    """Raised when a gated call is denied. Message is operator-facing."""


class BackupEngine:
    """Pre-flight backup engine. Replaced by the DirectAdmin engine in a later
    build step; the dev default records a placeholder reference so the flow is
    exercisable end to end."""

    async def create(self, site: Site, tier: BackupTier) -> str:
        return f"devbackup:{site.slug}:{tier.value}:{_secrets.token_hex(4)}"


@dataclass
class _WriteSpec:
    tier: Tier
    backup_tier: BackupTier
    planner: Planner
    applier: Applier


def _input_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _plan_id() -> str:
    return _secrets.token_hex(3)  # short, operator-friendly


class Gate:
    def __init__(self, store: Store, approver: Approver, cfg: Config,
                 backup_engine: BackupEngine | None = None) -> None:
        self.store = store
        self.approver = approver
        self.cfg = cfg
        self.backups = backup_engine or BackupEngine()
        self._writes: dict[str, _WriteSpec] = {}

    # --- registration ---
    def register_write(self, tool: str, tier: Tier, backup_tier: BackupTier,
                       planner: Planner, applier: Applier) -> None:
        if tier not in (Tier.R1, Tier.R2):
            raise ValueError("register_write is for R1/R2 only")
        self._writes[tool] = _WriteSpec(tier, backup_tier, planner, applier)

    # --- audit helper for R0 reads ---
    def audit(self, site: str | None, tool: str, tier: Tier, params: dict,
              outcome: str, summary: str | None = None, plan_id: str | None = None) -> None:
        self.store.record_audit(AuditEntry(
            site=site, tool=tool, tier=tier, input_hash=_input_hash(params),
            outcome=outcome, plan_id=plan_id, result_summary=summary,
        ))

    def _require_site(self, slug: str) -> Site:
        site = self.store.get_site(slug)
        if site is None:
            raise GateError(f"unknown site slug: {slug!r}")
        return site

    # --- write: plan ---
    async def plan(self, tool: str, site_slug: str, params: dict) -> dict:
        spec = self._writes.get(tool)
        if spec is None:
            raise GateError(f"{tool} is not a registered write tool")
        site = self._require_site(site_slug)

        diff_text, target_hash = await spec.planner(site, params)
        plan = Plan(
            id=_plan_id(), site=site.slug, tool=tool, tier=spec.tier, params=params,
            ttl_expires_at=utcnow() + timedelta(seconds=self.cfg.plan_ttl_seconds),
            diff_text=diff_text, target_hash=target_hash, backup_tier=spec.backup_tier,
            status=PlanStatus.PENDING,
        )
        self.store.create_plan(plan)
        await self.approver.request(plan, diff_text or "(no diff)")

        out = {
            "plan_id": plan.id,
            "tier": spec.tier.value,
            "site": site.slug,
            "tool": tool,
            "diff": diff_text,
            "backup_tier": spec.backup_tier.value,
            "expires_at": plan.ttl_expires_at.isoformat(),
            "approver": self.approver.name,
        }
        if not self.approver.polls:
            out["confirm_token"] = confirm_token(plan)
            out["how_to_apply"] = (
                f"Have the operator confirm, then call apply_plan(plan_id='{plan.id}', "
                f"confirm_token='{confirm_token(plan)}')."
            )
        else:
            out["how_to_apply"] = (
                f"Approval was sent via {self.approver.name}. Once approved, call "
                f"apply_plan(plan_id='{plan.id}')."
            )
        self.audit(site.slug, tool, spec.tier, params, "ok", "planned", plan.id)
        return out

    # --- write: apply ---
    async def apply_plan(self, plan_id: str, confirm_token: str | None = None) -> dict:
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise GateError(f"unknown plan: {plan_id!r}")
        spec = self._writes.get(plan.tool)
        if spec is None:
            raise GateError(f"plan references unknown tool {plan.tool!r}")

        # --- preconditions ---
        if plan.used or plan.status == PlanStatus.APPLIED:
            raise GateError(f"plan {plan_id} already used (single-use)")
        if plan.status == PlanStatus.REJECTED:
            raise GateError(f"plan {plan_id} was rejected")
        if plan.is_expired():
            plan.status = PlanStatus.EXPIRED
            self.store.update_plan(plan)
            self.audit(plan.site, plan.tool, plan.tier, plan.params, "denied", "expired", plan_id)
            raise GateError(f"plan {plan_id} expired; re-plan to get a fresh preview")

        # --- approval ---
        if self.approver.polls:
            if plan.status != PlanStatus.APPROVED:
                raise GateError(f"plan {plan_id} not approved yet via {self.approver.name}")
        else:
            if not self.approver.verify_token(plan, confirm_token):
                self.audit(plan.site, plan.tool, plan.tier, plan.params, "denied",
                           "bad confirm token", plan_id)
                raise GateError("invalid or missing confirm_token; operator must confirm the plan")

        site = self._require_site(plan.site)

        # --- serialize writes on this site ---
        if not self.store.try_acquire_lock(site.slug, plan.id):
            raise GateError(f"another write is in progress on {site.slug}; retry shortly")
        try:
            # --- drift guard: target must match what the plan previewed ---
            _, current_hash = await spec.planner(site, plan.params)
            if plan.target_hash is not None and current_hash is not None \
                    and current_hash != plan.target_hash:
                self.audit(site.slug, plan.tool, plan.tier, plan.params, "denied",
                           "target drifted since plan", plan_id)
                raise GateError(
                    f"target on {site.slug} changed since the plan was made; re-plan to refresh")

            # --- pre-flight backup (R2 / any non-none backup tier) ---
            if plan.backup_tier != BackupTier.NONE:
                plan.preflight_backup_ref = await self.backups.create(site, plan.backup_tier)
                self.store.update_plan(plan)

            # --- execute ---
            try:
                result = await spec.applier(site, plan.params, plan)
            except Exception as e:
                plan.status = PlanStatus.FAILED
                plan.result = {"error": str(e), "rollback_ref": plan.preflight_backup_ref}
                self.store.update_plan(plan)
                self.audit(site.slug, plan.tool, plan.tier, plan.params, "error",
                           f"apply failed: {e}", plan_id)
                raise GateError(
                    f"apply failed: {e}. "
                    + (f"Restore from backup {plan.preflight_backup_ref}."
                       if plan.preflight_backup_ref else "No backup was taken (R1).")
                )

            plan.status = PlanStatus.APPLIED
            plan.used = True
            plan.applied_at = utcnow()
            plan.result = result
            self.store.update_plan(plan)
            self.audit(site.slug, plan.tool, plan.tier, plan.params, "ok", "applied", plan_id)
            return {
                "plan_id": plan.id, "status": "applied", "result": result,
                "backup_ref": plan.preflight_backup_ref,
            }
        finally:
            self.store.release_lock(site.slug, plan.id)

    # --- write: reject ---
    def reject_plan(self, plan_id: str, by: str = "operator") -> dict:
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise GateError(f"unknown plan: {plan_id!r}")
        plan.status = PlanStatus.REJECTED
        plan.approved_by = by
        self.store.update_plan(plan)
        self.audit(plan.site, plan.tool, plan.tier, plan.params, "denied", "rejected", plan_id)
        return {"plan_id": plan_id, "status": "rejected"}

    # --- approval hook (out-of-band channels call this) ---
    def mark_approved(self, plan_id: str, by: str) -> None:
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise GateError(f"unknown plan: {plan_id!r}")
        if plan.status == PlanStatus.PENDING:
            plan.status = PlanStatus.APPROVED
            plan.approved_by = by
            self.store.update_plan(plan)
