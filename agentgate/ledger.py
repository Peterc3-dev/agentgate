"""Transaction ledger for tracking spending history.

The ledger is what makes velocity checks, daily/weekly/monthly limits,
and "new merchant" detection possible. It's an in-memory store by default,
with a protocol for plugging in persistent backends.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .models import Transaction


class LedgerBackend(Protocol):
    """Protocol for persistent ledger backends."""

    def record(self, agent_id: str, transaction: Transaction) -> None: ...
    def get_transactions(
        self, agent_id: str, since: datetime
    ) -> list[Transaction]: ...
    def get_known_merchants(self, agent_id: str) -> set[str]: ...
    def get_known_categories(self, agent_id: str) -> set[str]: ...


class InMemoryLedger:
    """In-memory transaction ledger. Good for dev/testing, not production."""

    def __init__(self):
        self._transactions: dict[str, list[Transaction]] = defaultdict(list)
        self._known_merchants: dict[str, set[str]] = defaultdict(set)
        self._known_categories: dict[str, set[str]] = defaultdict(set)

    def record(self, agent_id: str, transaction: Transaction) -> None:
        self._transactions[agent_id].append(transaction)
        self._known_merchants[agent_id].add(transaction.merchant)
        self._known_categories[agent_id].add(transaction.category)

    def get_transactions(
        self, agent_id: str, since: datetime
    ) -> list[Transaction]:
        return [
            tx
            for tx in self._transactions.get(agent_id, [])
            if tx.timestamp >= since
        ]

    def get_known_merchants(self, agent_id: str) -> set[str]:
        return self._known_merchants.get(agent_id, set())

    def get_known_categories(self, agent_id: str) -> set[str]:
        return self._known_categories.get(agent_id, set())

    def total_since(self, agent_id: str, since: datetime) -> float:
        return sum(tx.amount for tx in self.get_transactions(agent_id, since))

    def count_since(self, agent_id: str, since: datetime) -> int:
        return len(self.get_transactions(agent_id, since))

    def last_transaction_time(self, agent_id: str) -> datetime | None:
        txs = self._transactions.get(agent_id, [])
        return txs[-1].timestamp if txs else None

    def clear(self, agent_id: str | None = None) -> None:
        if agent_id:
            self._transactions.pop(agent_id, None)
            self._known_merchants.pop(agent_id, None)
            self._known_categories.pop(agent_id, None)
        else:
            self._transactions.clear()
            self._known_merchants.clear()
            self._known_categories.clear()
