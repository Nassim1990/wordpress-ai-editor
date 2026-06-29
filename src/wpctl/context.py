"""Dependency container wiring config -> store, secrets, executors, gate."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .executors import RestClient, SSHRunner
from .gating import Gate, build_approver
from .secrets import SecretResolver, build_secret_resolver
from .store import Store, build_store


@dataclass
class AppContext:
    cfg: Config
    store: Store
    secrets: SecretResolver
    ssh: SSHRunner
    rest: RestClient
    gate: Gate

    @classmethod
    def build(cls, cfg: Config | None = None) -> "AppContext":
        cfg = cfg or Config.from_env()
        store = build_store(cfg)
        secrets = build_secret_resolver(cfg)
        approver = build_approver(cfg)
        return cls(
            cfg=cfg,
            store=store,
            secrets=secrets,
            ssh=SSHRunner(secrets),
            rest=RestClient(secrets),
            gate=Gate(store, approver, cfg),
        )
