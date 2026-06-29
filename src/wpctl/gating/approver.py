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
  - TelegramApprover: out-of-band approval for the unattended/automation case.
    `request` pushes the diff with Approve/Reject buttons; a webhook (see
    docs) flips the plan status. Holds up when no human is watching the chat.
  - AutoApprover: dev only. Approves immediately, no human. Never use in prod.
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
    # poll (telegram, dashboard). False if approval is proven at apply time by a
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


class TelegramApprover:
    name = "telegram"
    polls = True

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def request(self, plan: Plan, summary: str) -> None:
        import httpx

        text = f"\U0001f512 *{plan.tool}* on *{plan.site}* ({plan.tier.value})\n\n{summary}"
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{plan.id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{plan.id}"},
            ]]
        }
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text,
                      "parse_mode": "Markdown", "reply_markup": keyboard},
            )

    def verify_token(self, plan: Plan, token: str | None) -> bool:
        # Approval comes via the webhook updating plan.status; no token needed.
        return True


def build_approver(cfg: Config) -> Approver:
    if cfg.approver == "chat_token":
        return ChatTokenApprover()
    if cfg.approver == "auto":
        return AutoApprover()
    if cfg.approver == "telegram":
        if not (cfg.telegram_bot_token and cfg.telegram_chat_id):
            raise RuntimeError("WPCTL_APPROVER=telegram requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return TelegramApprover(cfg.telegram_bot_token, cfg.telegram_chat_id)
    raise RuntimeError(f"unknown WPCTL_APPROVER: {cfg.approver!r}")
