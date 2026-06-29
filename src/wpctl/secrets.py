"""Secret resolution.

Sites store *references* (e.g. ssh_key_ref="BOUCHERIE_SSH_KEY"). The resolver
turns a ref into real secret material server-side. Resolved secrets are used by
executors and are NEVER returned to Claude / included in tool output.
"""

from __future__ import annotations

import os
from typing import Protocol

from .config import Config


class SecretResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


class EnvSecretResolver:
    """Dev resolver: a ref names an environment variable."""

    def resolve(self, ref: str) -> str:
        val = os.getenv(ref)
        if val is None:
            raise KeyError(f"secret ref {ref!r} not found in environment")
        return val


def build_secret_resolver(cfg: Config) -> SecretResolver:
    if cfg.secrets == "env":
        return EnvSecretResolver()
    raise RuntimeError(f"unknown WPCTL_SECRETS: {cfg.secrets!r}")
