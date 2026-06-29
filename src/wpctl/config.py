"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    store: str
    sqlite_path: str
    supabase_url: str | None
    supabase_key: str | None
    approver: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    plan_ttl_seconds: int
    secrets: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            store=os.getenv("WPCTL_STORE", "sqlite"),
            sqlite_path=os.getenv("WPCTL_SQLITE_PATH", "wpctl.sqlite"),
            supabase_url=os.getenv("SUPABASE_URL") or None,
            supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None,
            approver=os.getenv("WPCTL_APPROVER", "auto"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            plan_ttl_seconds=int(os.getenv("WPCTL_PLAN_TTL_SECONDS", "900")),
            secrets=os.getenv("WPCTL_SECRETS", "env"),
        )
