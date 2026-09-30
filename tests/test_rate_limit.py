from app.rate_limit import SlidingWindowLimiter


def test_sliding_window():
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_s=10, clock=lambda: now[0])
    assert limiter.allow() and limiter.allow()
    assert not limiter.allow()
    now[0] = 10.0  # first hits expire
    assert limiter.allow()
