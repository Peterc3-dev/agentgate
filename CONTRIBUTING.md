# Contributing to AgentGate

## Quick Start

1. Fork the repo
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/agentgate.git`
3. Install dev dependencies: `pip install -e ".[dev]"`
4. Run tests: `pytest tests/ -v`
5. Make your changes on a branch
6. Submit a PR

## Good First Issues

Look for the `good first issue` label. These are scoped, self-contained tasks:

- **Redis ledger backend** — implement `LedgerBackend` protocol with Redis
- **SQLite ledger backend** — persistent local ledger for single-machine deployments
- **Policy validation** — catch contradictory rules (e.g., allowed and blocked at the same time)
- **Currency conversion** — support multi-currency limits

## Rules

- Every PR must pass CI (pytest across Python 3.10-3.12)
- New features need tests
- Keep dependencies minimal — zero required deps is a feature

## Architecture

- `models.py` — data classes, no logic
- `checks.py` — pure functions, each check is independent
- `gate.py` — orchestrates checks, writes audit log
- `ledger.py` — transaction history, pluggable backends
- `decorators.py` — `@gated` wrapper for payment functions
- `loader.py` — YAML policy parsing

## Adding a New Check

1. Write a function in `checks.py` following the signature: `(tx, policy, ledger, **_) -> Check`
2. Add it to `ALL_CHECKS` list
3. Add tests
4. That's it

## Adding a Ledger Backend

1. Implement the `LedgerBackend` protocol in a new file
2. Add tests
3. Add to `__init__.py` exports
