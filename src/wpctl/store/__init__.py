"""Store factory."""

from __future__ import annotations

from ..config import Config
from .base import Store


def build_store(cfg: Config) -> Store:
    if cfg.store == "sqlite":
        from .sqlite_store import SQLiteStore

        return SQLiteStore(cfg.sqlite_path)
    if cfg.store == "supabase":
        from .supabase_store import SupabaseStore

        if not (cfg.supabase_url and cfg.supabase_key):
            raise RuntimeError("WPCTL_STORE=supabase requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        return SupabaseStore(cfg.supabase_url, cfg.supabase_key)
    raise RuntimeError(f"unknown WPCTL_STORE: {cfg.store!r}")


__all__ = ["Store", "build_store"]
