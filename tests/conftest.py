from __future__ import annotations

import pytest


class FakeClock:
    """sleep() すると時間が進む、テスト用の時計。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
