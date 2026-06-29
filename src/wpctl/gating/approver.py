"""Approver — the human-in-the-loop confirm channel (pluggable).

The gate creates a plan in `pending` status and calls `request(plan)` to notify
the operator. Approval is recorded out of band (the operator acts), and the gate
only applies a plan whose status has become `approved`.

Implementations:
  - ChatTokenApprover (default, for Claude Cowork): the operator confirms inline
    in chat by relaying the plan's confirm token to `apply_plan`. This is what
    makes the gate real in an interactive session — the token is shown to the
    operator at plan time and must be echoed back to apply. Cowork's own
    per-call tool-approval prompt is an additional layer.
  - AutoApprover: dev only. Approves immediately, no human. Never use in prod.

A future out-of-band channel (e.g. an approval dashboard) can be added as a
`polls=True` approver whose external action flips the plan to `approved`; the
gate already supports that path (`apply_plan` checks status for polling
approvers). No such channel is implemented today.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from ..config import Config
from ..models import Plan


def confirm_token(plan: Plan) -> str:
    """Short, deterministic token derived from the plan id. Shown to the operator."""
    digest = hashlib.sha256(plan.id.encode()).hexdigest()[:6]
    return f"APPLY-{plan.id}-{digest}"


class Approver(Protocol):
    name: str
    # True if this channel approves via an out-of-band record the gate should
    # poll (e.g. a dashboard). False if approval is proven at apply time by a
    # token the operator relays (chat_token) — then verify_token is used instead.
    polls: bool

    async def request(self, plan: Plan, summary: str) -> None: ...
    def verify_token(self, plan: Plan, token: str | None) -> bool: ...


class ChatTokenApprover:
    name = "chat_token"
    polls = False

    async def request(self, plan: Plan, summary: str) -> None:
        # Nothing to deliver: the token is returned to Claude by the plan_* tool
        # and Claude shows it to the operator in the Cowork chat.
        return None

    def verify_token(self, plan: Plan, token: str | None) -> bool:
        if not token:
            return False
        return token.strip() == confirm_token(plan)


class AutoApprover:
    name = "auto"
    polls = False

    async def request(self, plan: Plan, summary: str) -> None:
        return None

    def verify_token(self, plan: Plan, token: str | None) -> bool:
        return True  # dev only


def build_approver(cfg: Config) -> Approver:
    if cfg.approver == "chat_token":
        return ChatTokenApprover()
    if cfg.approver == "auto":
        return AutoApprover()
    raise RuntimeError(f"unknown WPCTL_APPROVER: {cfg.approver!r}")
