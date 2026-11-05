"""The Gate — core evaluation engine."""

from __future__ import annotations

import dataclasses
import threading
import uuid
import warnings
from datetime import datetime, timezone
from typing import Callable, Protocol

from .checks import ALL_CHECKS
from .ledger import InMemoryLedger
from .models import (
    AuditEntry,
    Check,
    CheckResult,
    Decision,
    EvaluationResult,
    Policy,
    Transaction,
)


_RESERVATION_METHODS = ("reserve", "confirm", "release")


def _supports_reservations(ledger: object) -> bool:
    """True if the ledger implements the pending-reservation methods."""
    return all(callable(getattr(ledger, m, None)) for m in _RESERVATION_METHODS)


def _new_audit_id() -> str:
    return f"audit_{uuid.uuid4().hex[:12]}"


class EscalationHandler(Protocol):
    """Protocol for handling escalated transactions."""

    async def escalate(
        self, transaction: Transaction, reasons: list[str]
    ) -> bool:
        """Return True to approve, False to deny."""
        ...


class LoggingEscalationHandler:
    """Default escalation handler — logs and denies."""

    async def escalate(
        self, transaction: Transaction, reasons: list[str]
    ) -> bool:
        print(f"[ESCALATION] tx={transaction.id} reasons={reasons}")
        return False  # deny by default — safe fallback


class Gate:
    """Main policy evaluation engine.

    Usage:
        gate = Gate(policy=my_policy)
        result = gate.evaluate(transaction)
        if result.passed:
            # proceed with payment
        elif result.decision == Decision.ESCALATE:
            # human review needed
        else:
            # denied — result.failed_checks has details
    """

    def __init__(
        self,
        policy: Policy,
        ledger: InMemoryLedger | None = None,
        escalation_handler: EscalationHandler | None = None,
        checks: list[Callable] | None = None,
        audit_log: list[AuditEntry] | None = None,
    ):
        self.policy = policy
        self.ledger = ledger or InMemoryLedger()
        self._reservations = _supports_reservations(self.ledger)
        if not self._reservations:
            warnings.warn(
                f"{type(self.ledger).__name__} does not implement reserve/"
                "confirm/release; check() will not reserve spend and commit() "
                "will record the transaction. Concurrent check() calls can "
                "then both pass a cumulative limit only one of them fits. "
                "Implement the reservation methods to close that gap.",
                RuntimeWarning,
                stacklevel=2,
            )
        self.escalation_handler = escalation_handler
        self._checks = checks or ALL_CHECKS
        self._audit_log: list[AuditEntry] = audit_log if audit_log is not None else []
        # Serialises check-and-record so concurrent evaluations for the same
        # agent cannot both pass a cumulative limit (e.g. daily) and both record.
        self._lock = threading.RLock()

    def evaluate(self, tx: Transaction) -> EvaluationResult:
        """Evaluate a transaction and, if allowed, record it in the ledger."""
        return self._evaluate(tx, mode="record")

    def check(self, tx: Transaction) -> EvaluationResult:
        """Evaluate a transaction and, if allowed, reserve it in the ledger.

        The reservation is made under the same lock as the checks and counts
        toward cumulative limits and velocity, so two concurrent check() calls
        cannot both pass a limit that only one of them fits. Once the payment
        has gone through, call commit(tx); if it fails, call release(tx).
        """
        return self._evaluate(tx, mode="reserve")

    def commit(self, tx: Transaction) -> None:
        """Record a completed transaction.

        Confirms the reservation made by check(). A transaction with no
        reservation is recorded directly, stamped with now.
        """
        with self._lock:
            if not self._reservations or not self.ledger.confirm(tx.agent_id, tx.id):
                self.ledger.record(tx.agent_id, self._stamped(tx))

    def release(self, tx: Transaction) -> None:
        """Drop the reservation made by check() for a payment that failed."""
        if not self._reservations:
            return
        with self._lock:
            self.ledger.release(tx.agent_id, tx.id)

    @staticmethod
    def _stamped(tx: Transaction) -> Transaction:
        # Stamp the recorded time ourselves: a caller-supplied timestamp
        # could be backdated to fall outside every window.
        return dataclasses.replace(tx, timestamp=datetime.now(timezone.utc))

    async def evaluate_async(self, tx: Transaction) -> EvaluationResult:
        """Evaluate a transaction, consulting the escalation handler if needed.

        Runs the same checks as evaluate(). If the decision is ESCALATE and an
        escalation_handler is set, the spend is reserved while the handler
        decides, so concurrent transactions cannot use the same headroom. On
        approval the transaction is recorded and the result is ALLOW; on
        rejection the reservation is released and the result is DENY. Both
        outcomes append an audit entry with escalation_outcome set.

        Without a handler this behaves like evaluate() and an escalated
        transaction is returned as ESCALATE without being recorded.
        """
        return await self._evaluate_async(tx, mode="record")

    async def check_async(self, tx: Transaction) -> EvaluationResult:
        """Like check(), but resolves ESCALATE through the escalation handler.

        On approval the reservation is kept and the result is ALLOW; the
        caller must then commit(tx) or release(tx) as with check().
        """
        return await self._evaluate_async(tx, mode="reserve")

    async def _evaluate_async(self, tx: Transaction, mode: str) -> EvaluationResult:
        handler = self.escalation_handler
        if handler is None:
            return self._evaluate(tx, mode=mode)

        result = self._evaluate(tx, mode=mode, reserve_escalated=True)
        if result.decision != Decision.ESCALATE:
            return result

        try:
            approved = await handler.escalate(tx, list(result.escalation_reasons))
        except BaseException:
            self.release(tx)
            raise

        if approved is True:
            if mode == "record":
                self.commit(tx)
            decision, outcome = Decision.ALLOW, "approved"
        else:
            self.release(tx)
            decision, outcome = Decision.DENY, "rejected"

        audit = dataclasses.replace(
            result.audit,
            id=_new_audit_id(),
            timestamp=datetime.now(timezone.utc),
            decision=decision,
            escalation_outcome=outcome,
        )
        with self._lock:
            self._audit_log.append(audit)
        return dataclasses.replace(result, decision=decision, audit=audit)

    def _evaluate(
        self, tx: Transaction, mode: str, reserve_escalated: bool = False
    ) -> EvaluationResult:
        with self._lock:
            results: list[Check] = []
            escalation_reasons: list[str] = []

            for check_fn in self._checks:
                check = check_fn(tx=tx, policy=self.policy, ledger=self.ledger)
                results.append(check)

            # Separate hard failures from escalation
            hard_fails = [
                c for c in results
                if c.result == CheckResult.FAIL and c.name != "escalation"
            ]
            escalation_check = next(
                (c for c in results if c.name == "escalation"), None
            )

            # Determine decision
            if hard_fails:
                decision = Decision.DENY
            elif escalation_check and escalation_check.result == CheckResult.FAIL:
                decision = Decision.ESCALATE
                escalation_reasons = escalation_check.details.get("reasons", [])
            else:
                decision = Decision.ALLOW

            # Build audit entry
            audit = AuditEntry(
                timestamp=datetime.now(timezone.utc),
                transaction_id=tx.id,
                agent_id=tx.agent_id,
                decision=decision,
                checks_passed=[c.name for c in results if c.result == CheckResult.PASS],
                checks_failed=[c.name for c in results if c.result == CheckResult.FAIL],
                escalation_reasons=escalation_reasons,
                reasoning=tx.reasoning,
                policy_name=self.policy.name,
                policy_version=self.policy.version,
            )
            self._audit_log.append(audit)

            # Record (or reserve) in ledger if allowed. An escalated
            # transaction awaiting a handler is held as a reservation.
            # A backend without reservations records at commit() instead.
            if decision == Decision.ESCALATE and reserve_escalated:
                if self._reservations:
                    self.ledger.reserve(tx.agent_id, self._stamped(tx))
            elif decision == Decision.ALLOW:
                if mode == "record":
                    self.ledger.record(tx.agent_id, self._stamped(tx))
                elif mode == "reserve" and self._reservations:
                    self.ledger.reserve(tx.agent_id, self._stamped(tx))

            result = EvaluationResult(
                decision=decision,
                transaction=tx,
                checks=results,
                escalation_reasons=escalation_reasons,
                audit=audit,
            )
            return result

    @property
    def audit_log(self) -> list[AuditEntry]:
        return list(self._audit_log)

    def reset(self) -> None:
        """Clear ledger and audit log. Useful for testing."""
        self.ledger.clear()
        self._audit_log.clear()
