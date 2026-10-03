import pytest

from scout.dsa.token_bucket import TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make(rate: float, capacity: float = 1.0) -> tuple[TokenBucket, FakeClock]:
    clock = FakeClock()
    return TokenBucket(rate, capacity, clock=clock, sleep=clock.sleep), clock


def test_burst_then_waits_at_rate() -> None:
    bucket, clock = make(rate=2.0, capacity=3)
    waits = [bucket.acquire() for _ in range(5)]
    assert waits[:3] == [0.0, 0.0, 0.0]
    assert waits[3:] == pytest.approx([0.5, 0.5])
    assert clock.now == pytest.approx(1.0)


def test_transfermarkt_rate_spaces_requests_three_seconds() -> None:
    bucket, clock = make(rate=1 / 3, capacity=1)
    for _ in range(4):
        bucket.acquire()
    assert clock.now == pytest.approx(9.0)


def test_refill_caps_at_capacity() -> None:
    bucket, clock = make(rate=1.0, capacity=2)
    bucket.acquire()
    bucket.acquire()
    clock.now += 100
    assert bucket.tokens == pytest.approx(2.0)


def test_try_acquire_does_not_sleep() -> None:
    bucket, clock = make(rate=1.0, capacity=1)
    assert bucket.try_acquire()
    assert not bucket.try_acquire()
    assert clock.slept == []
    clock.now += 1.0
    assert bucket.try_acquire()


@pytest.mark.parametrize(("rate", "capacity"), [(0.0, 1.0), (-1.0, 1.0), (1.0, 0.5)])
def test_invalid_parameters(rate: float, capacity: float) -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate, capacity)


def test_acquire_more_than_capacity_rejected() -> None:
    bucket, _ = make(rate=1.0, capacity=1)
    with pytest.raises(ValueError):
        bucket.acquire(2)


def test_matches_reference_schedule() -> None:
    """Reference: with capacity c and rate r, request i (0-based) starts at max(0, (i-c+1)/r)."""
    rate, capacity, n = 0.5, 2, 8
    bucket, clock = make(rate, capacity)
    starts = []
    for _ in range(n):
        bucket.acquire()
        starts.append(clock.now)
    expected = [max(0.0, (i - capacity + 1) / rate) for i in range(n)]
    assert starts == pytest.approx(expected)
