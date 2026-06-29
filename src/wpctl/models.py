"""Domain models shared across the spine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tier(str, Enum):
    R0 = "R0"  # read, no gate
    R1 = "R1"  # reversible write: snapshot + confirm
    R2 = "R2"  # destructive: plan/apply + pre-flight backup


class PlanStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    EXPIRED = "expired"
    FAILED = "failed"


class BackupTier(str, Enum):
    NONE = "none"
    FILE = "file"
    DB = "db"
    ACCOUNT = "account"


@dataclass
class Site:
    slug: str
    domain: str
    wp_path: str
    ssh_host: str | None = None
    ssh_user: str | None = None
    ssh_port: int = 22
    ssh_key_ref: str | None = None
    rest_base: str | None = None
    app_password_ref: str | None = None
    app_user: str | None = None
    da_host: str | None = None
    da_account: str | None = None
    dns_provider: str = "directadmin"
    active: bool = True
    notes: str | None = None

    @property
    def resolved_rest_base(self) -> str:
        return self.rest_base or f"https://{self.domain}/wp-json"


@dataclass
class Plan:
    id: str
    site: str
    tool: str
    tier: Tier
    params: dict[str, Any]
    ttl_expires_at: datetime
    diff_text: str | None = None
    target_hash: str | None = None
    backup_tier: BackupTier = BackupTier.NONE
    preflight_backup_ref: str | None = None
    snapshot_ref: str | None = None
    status: PlanStatus = PlanStatus.PENDING
    approved_by: str | None = None
    used: bool = False
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utcnow)
    applied_at: datetime | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or utcnow()) >= self.ttl_expires_at


@dataclass
class AuditEntry:
    site: str | None
    tool: str
    tier: Tier
    input_hash: str
    outcome: str  # ok | error | denied
    plan_id: str | None = None
    actor: str = "claude"
    result_summary: str | None = None
    ts: datetime = field(default_factory=utcnow)
