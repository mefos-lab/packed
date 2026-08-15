"""Shared test configuration.

**The suite must not pay production rate limits.** `api_call` throttles
every request through a module-level limiter — 4s between OpenFEC calls,
0.6s for LDA — which is right against the real APIs and pure waiting
against a mock transport. A pattern making five calls slept 20 seconds
per test, and the suite took seven minutes to assert on canned JSON.

Only the shared singleton is neutralised. `tests/test_errors.py`
constructs its own `_ServiceRateLimiter` to check the throttling itself,
and those tests keep working because they never touch this instance.
"""

import pytest

from packed import errors


class _NoWaitLimiter:
    """Stands in for the shared limiter, without the sleeping."""

    async def wait(self, service: str) -> None:
        return None


@pytest.fixture(autouse=True)
def no_rate_limiting(monkeypatch):
    monkeypatch.setattr(errors, "_rate_limiter", _NoWaitLimiter())
