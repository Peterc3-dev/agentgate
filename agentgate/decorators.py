"""Decorators for wrapping payment functions with gate enforcement."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from .gate import Gate
from .models import Decision, Policy, Transaction


class GatedTransactionDenied(Exception):
    """Raised when a gated transaction is denied."""

    def __init__(self, result):
        self.result = result
        reasons = "; ".join(c.message for c in result.failed_checks)
        super().__init__(f"Transaction denied: {reasons}")


class GatedTransactionEscalated(Exception):
    """Raised when a gated transaction requires escalation."""

    def __init__(self, result):
        self.result = result
        super().__init__(f"Transaction requires escalation: {', '.join(result.escalation_reasons)}")


def gated(
    policy: Policy | None = None,
    gate: Gate | None = None,
    amount_param: str = "amount",
    merchant_param: str = "merchant",
    category_param: str = "category",
    agent_id: str = "default-agent",
    reasoning_param: str | None = None,
):
    """Decorator that gates a payment function behind policy evaluation.

    Usage:
        @gated(policy=my_policy)
        async def buy_item(merchant, amount, item):
            return await stripe.checkout(...)

        # Or with an existing gate:
        @gated(gate=my_gate, amount_param="price")
        def purchase(store, price):
            ...

    The decorated function will raise GatedTransactionDenied if the
    transaction is denied, or GatedTransactionEscalated if it needs
    human approval.
    """
    if policy is None and gate is None:
        raise ValueError("Either policy or gate must be provided")

    _gate = gate or Gate(policy=policy)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Extract transaction params from the function call
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()

            amount = bound.arguments.get(amount_param, 0)
            merchant = bound.arguments.get(merchant_param, "unknown")
            category = bound.arguments.get(category_param, "general")
            reasoning = ""
            if reasoning_param:
                reasoning = bound.arguments.get(reasoning_param, "")

            tx = Transaction(
                amount=float(amount),
                currency="USD",
                merchant=str(merchant),
                category=str(category),
                agent_id=agent_id,
                reasoning=reasoning,
            )

            result = _gate.evaluate(tx)

            if result.decision == Decision.DENY:
                raise GatedTransactionDenied(result)
            elif result.decision == Decision.ESCALATE:
                raise GatedTransactionEscalated(result)

            return func(*args, **kwargs)

        # Async variant
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()

            amount = bound.arguments.get(amount_param, 0)
            merchant = bound.arguments.get(merchant_param, "unknown")
            category = bound.arguments.get(category_param, "general")
            reasoning = ""
            if reasoning_param:
                reasoning = bound.arguments.get(reasoning_param, "")

            tx = Transaction(
                amount=float(amount),
                currency="USD",
                merchant=str(merchant),
                category=str(category),
                agent_id=agent_id,
                reasoning=reasoning,
            )

            result = _gate.evaluate(tx)

            if result.decision == Decision.DENY:
                raise GatedTransactionDenied(result)
            elif result.decision == Decision.ESCALATE:
                raise GatedTransactionEscalated(result)

            return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator
