"""Unit tests for copilot sliding window rate limiting."""

import pytest
from nexafreight.api.routes.copilot import (
    COPILOT_MAX_REQUESTS_PER_WINDOW,
    check_copilot_rate_limit,
    reset_copilot_rate_limits,
)
from nexafreight.exceptions import RateLimitExceededError


@pytest.fixture(autouse=True)
def clean_rate_limits():
    reset_copilot_rate_limits()
    yield
    reset_copilot_rate_limits()


def test_copilot_rate_limit_allows_under_cap():
    user_id = "user_test_1"
    for _ in range(COPILOT_MAX_REQUESTS_PER_WINDOW):
        check_copilot_rate_limit(user_id)


def test_copilot_rate_limit_rejects_over_cap():
    user_id = "user_test_2"
    for _ in range(COPILOT_MAX_REQUESTS_PER_WINDOW):
        check_copilot_rate_limit(user_id)

    with pytest.raises(RateLimitExceededError) as exc_info:
        check_copilot_rate_limit(user_id)

    assert exc_info.value.status_code == 429
    assert "Copilot rate limit exceeded" in exc_info.value.message


def test_copilot_rate_limit_isolated_per_user():
    user_a = "user_a"
    user_b = "user_b"

    for _ in range(COPILOT_MAX_REQUESTS_PER_WINDOW):
        check_copilot_rate_limit(user_a)

    # user_a is now rate-limited
    with pytest.raises(RateLimitExceededError):
        check_copilot_rate_limit(user_a)

    # user_b is not rate-limited
    check_copilot_rate_limit(user_b)
