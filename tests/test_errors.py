"""Tests for error handling, retries, and rate limiting."""

import asyncio
import time
import pytest
import httpx

from packed.errors import (
    ServiceTracker, ServiceError, api_call,
    SERVICE_RATE_LIMITS, _ServiceRateLimiter, _is_retryable,
)


async def _async_ok():
    return {"ok": True}


# =============================================================================
# ServiceTracker tests
# =============================================================================

class TestServiceTracker:
    def test_record_http_error(self):
        tracker = ServiceTracker()
        resp = httpx.Response(500, text='{"code":500,"message":"Server Error"}')
        exc = httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)
        tracker.record("OpenFEC", "/candidates/search/", exc)

        assert len(tracker.errors) == 1
        assert tracker.errors[0].service == "OpenFEC"
        assert tracker.errors[0].endpoint == "/candidates/search/"
        assert tracker.errors[0].status_code == 500
        assert "500" in tracker.errors[0].message

    def test_record_timeout(self):
        tracker = ServiceTracker()
        tracker.record("LDA", "/filings/public/filing/search/", httpx.ReadTimeout("timed out"))

        assert tracker.errors[0].status_code is None
        assert "timed out" in tracker.errors[0].message

    def test_record_connection_error(self):
        tracker = ServiceTracker()
        tracker.record("ProPublica NPE", "/organizations", httpx.ConnectError("refused"))

        assert "connection failed" in tracker.errors[0].message

    def test_warnings_deduplicates(self):
        tracker = ServiceTracker()
        resp = httpx.Response(502)
        exc = httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)
        tracker.record("OpenFEC", "/committees/", exc)
        tracker.record("OpenFEC", "/committees/", exc)
        tracker.record("OpenFEC", "/committees/", exc)

        warnings = tracker.warnings
        assert len(warnings) == 1
        assert "(3 failures)" in warnings[0]
        assert "OpenFEC" in warnings[0]

    def test_warnings_multiple_services(self):
        tracker = ServiceTracker()
        resp500 = httpx.Response(500)
        resp502 = httpx.Response(502)
        exc500 = httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp500)
        exc502 = httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp502)
        tracker.record("OpenFEC", "/candidates/search/", exc500)
        tracker.record("LDA", "/filings/public/filing/search/", exc502)

        assert len(tracker.warnings) == 2

    def test_failed_services(self):
        tracker = ServiceTracker()
        resp = httpx.Response(500)
        exc = httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)
        tracker.record("OpenFEC", "/candidates/search/", exc)
        tracker.record("OpenFEC", "/committees/", exc)
        tracker.record("LDA", "/filings/public/filing/search/", exc)

        assert tracker.failed_services == ["LDA", "OpenFEC"]

    def test_to_dict(self):
        tracker = ServiceTracker()
        resp = httpx.Response(429)
        exc = httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)
        tracker.record("OpenFEC", "/schedules/schedule_a/", exc)

        d = tracker.to_dict()
        assert d["error_count"] == 1
        assert len(d["warnings"]) == 1
        assert d["failed_services"] == ["OpenFEC"]
        assert d["errors"][0]["status_code"] == 429

    def test_empty_tracker(self):
        tracker = ServiceTracker()
        assert tracker.warnings == []
        assert tracker.failed_services == []
        assert tracker.to_dict()["error_count"] == 0


# =============================================================================
# _is_retryable tests
# =============================================================================

class TestIsRetryable:
    @pytest.mark.parametrize("status_code,expected", [
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (422, False),
    ])
    def test_http_status_codes(self, status_code, expected):
        resp = httpx.Response(status_code)
        exc = httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)
        assert _is_retryable(exc) == expected

    def test_timeout_is_retryable(self):
        assert _is_retryable(httpx.ReadTimeout("")) is True

    def test_connect_error_is_retryable(self):
        assert _is_retryable(httpx.ConnectError("")) is True

    def test_value_error_not_retryable(self):
        assert _is_retryable(ValueError("bad")) is False


# =============================================================================
# api_call tests
# =============================================================================

class TestApiCall:
    @pytest.mark.asyncio
    async def test_success(self):
        tracker = ServiceTracker()
        result = await api_call(tracker, "OpenFEC", "/candidates/search/",
                                lambda: _async_ok())
        assert result == {"ok": True}
        assert len(tracker.errors) == 0

    @pytest.mark.asyncio
    async def test_success_with_coroutine(self):
        """Bare coroutine (no retry) still works."""
        tracker = ServiceTracker()

        async def coro():
            return {"ok": True}

        result = await api_call(tracker, "OpenFEC", "/candidates/search/", coro())
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_non_retryable_fails_immediately(self):
        tracker = ServiceTracker()
        call_count = 0

        async def failing():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        result = await api_call(tracker, "OpenFEC", "/candidates/search/",
                                lambda: failing(), max_retries=2)
        assert result is None
        assert call_count == 1  # no retries for non-retryable
        assert len(tracker.errors) == 1

    @pytest.mark.asyncio
    async def test_retries_on_500(self):
        tracker = ServiceTracker()
        call_count = 0

        async def sometimes_fails():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                resp = httpx.Response(500)
                raise httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)
            return {"recovered": True}

        result = await api_call(tracker, "OpenFEC", "/candidates/search/",
                                lambda: sometimes_fails(), max_retries=2)
        assert result == {"recovered": True}
        assert call_count == 3
        assert len(tracker.errors) == 0  # succeeded, so no error recorded

    @pytest.mark.asyncio
    async def test_exhausted_retries_records_error(self):
        tracker = ServiceTracker()

        async def always_fails():
            resp = httpx.Response(500)
            raise httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)

        result = await api_call(tracker, "OpenFEC", "/candidates/search/",
                                lambda: always_fails(), max_retries=2)
        assert result is None
        assert len(tracker.errors) == 1
        assert tracker.errors[0].status_code == 500

    @pytest.mark.asyncio
    async def test_coroutine_no_retry(self):
        """Bare coroutines can only be awaited once — no retry."""
        tracker = ServiceTracker()

        async def fails():
            resp = httpx.Response(500)
            raise httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=resp)

        result = await api_call(tracker, "OpenFEC", "/candidates/search/",
                                fails(), max_retries=2)
        assert result is None
        assert len(tracker.errors) == 1


# =============================================================================
# Rate limiter tests
# =============================================================================

class TestServiceRateLimiter:
    @pytest.mark.asyncio
    async def test_enforces_minimum_interval(self):
        limiter = _ServiceRateLimiter()
        # Use a known service
        start = time.monotonic()
        await limiter.wait("LDA")  # 0.6s interval
        await limiter.wait("LDA")
        elapsed = time.monotonic() - start
        # Second call should have waited ~0.6s
        assert elapsed >= 0.5

    @pytest.mark.asyncio
    async def test_different_services_independent(self):
        limiter = _ServiceRateLimiter()
        start = time.monotonic()
        await limiter.wait("OpenFEC")
        await limiter.wait("ProPublica NPE")  # different service, no wait
        elapsed = time.monotonic() - start
        # Should be nearly instant — different services don't block each other
        assert elapsed < 0.3

    @pytest.mark.asyncio
    async def test_unknown_service_no_throttle(self):
        limiter = _ServiceRateLimiter()
        start = time.monotonic()
        await limiter.wait("UnknownAPI")
        await limiter.wait("UnknownAPI")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1


# =============================================================================
# SERVICE_RATE_LIMITS registry
# =============================================================================

class TestRateLimitsRegistry:
    def test_all_known_services_have_limits(self):
        expected = {"OpenFEC", "LDA", "ProPublica NPE"}
        assert set(SERVICE_RATE_LIMITS.keys()) == expected

    def test_limits_are_positive(self):
        for service, interval in SERVICE_RATE_LIMITS.items():
            assert interval > 0, f"{service} has non-positive interval"

    def test_limits_are_reasonable(self):
        """No service should be slower than 5s between requests."""
        for service, interval in SERVICE_RATE_LIMITS.items():
            assert interval <= 5.0, f"{service} interval {interval}s seems too slow"
