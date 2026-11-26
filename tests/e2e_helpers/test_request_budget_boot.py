"""The request-budget probe moves to its next phase only once the page's traffic is quiet.

No browser: a fake page and a fake real-time clock replay requests the driver hears of
late. WebKit announces a second boot wave a fraction of a second after the first wave's
last `requestfinished`, and a read chained on an answer can arrive the same way at the
end of a minute: a probe that moves on the moment nothing is in flight counts it in the
wrong phase.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from tests.e2e.budget import _request_budget as probe
from tests.e2e.budget._request_budget import RequestBudgetUnknown, measure_request_budget

Event = tuple[float, Callable[[], None]]
_CURRENT: list[_FakePage] = []


class _Request:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakePage:
    """Real time passes only in `wait_for_timeout` and in a clock step, like the probe's own waits."""

    def __init__(self) -> None:
        self.now = 0.0
        _CURRENT.append(self)
        self.handlers: dict[str, list[Callable[[_Request], None]]] = {}
        self.events: list[Event] = []
        self.clock = SimpleNamespace(
            install=lambda: None, pause_at=lambda at: None, run_for=lambda ms: self._advance(0.005)
        )

    def on(self, name: str, handler: Callable[[_Request], None]) -> None:
        self.handlers.setdefault(name, []).append(handler)

    def add_init_script(self, script: str) -> None:
        pass

    def wait_for_load_state(self, state: str = "load", **kwargs: object) -> None:
        pass

    def evaluate(self, script: str) -> int:
        return 0

    def wait_for_timeout(self, ms: int) -> None:
        self._advance(ms / 1000)

    def goto(self, url: str) -> None:
        self.boot()

    def boot(self) -> None:
        raise NotImplementedError

    def request(self, path: str, at: float, answered_after: float = 0.02) -> None:
        """Announce `path` at `at` seconds from now and finish it `answered_after` later."""
        req = _Request(f"https://app.test{path}")
        self.events.append((self.now + at, lambda: self._emit("request", req)))
        self.events.append((self.now + at + answered_after, lambda: self._emit("requestfinished", req)))

    def _emit(self, name: str, req: _Request) -> None:
        for handler in self.handlers.get(name, []):
            handler(req)

    def _advance(self, seconds: float) -> None:
        self.now += seconds
        for event in sorted((e for e in self.events if e[0] <= self.now), key=lambda e: e[0]):
            self.events.remove(event)
            event[1]()


class _TwoWavePage(_FakePage):
    """Who-am-I first; the next wave is announced 0.25 s after it finished, like WebKit does."""

    def boot(self) -> None:
        self.request("/api/who", at=0.0, answered_after=0.05)
        for path in ("/api/tasks", "/api/today", "/api/projects"):
            self.request(path, at=0.3, answered_after=0.05)


class _NeverQuietPage(_FakePage):
    """A request every 0.1 s, each announced only after the last one finished."""

    def boot(self) -> None:
        for i in range(200):
            self.request("/api/spin", at=i * 0.1, answered_after=0.01)


class _LateChainPage(_FakePage):
    """A read the driver hears of just after the visible minute's last step has returned."""

    def boot(self) -> None:
        steps: list[int] = []

        def run_for(ms: int) -> None:
            steps.append(ms)
            if len(steps) == 4:
                self.request("/api/chained", at=0.01)
            self._advance(0.005)

        self.clock.run_for = run_for


@pytest.fixture(autouse=True)
def _fake_real_time(monkeypatch: pytest.MonkeyPatch) -> None:
    _CURRENT.clear()
    monkeypatch.setattr(probe, "time", SimpleNamespace(monotonic=lambda: _CURRENT[-1].now))


def test_a_second_boot_wave_is_not_the_visible_minute() -> None:
    reading = measure_request_budget(_TwoWavePage(), "https://app.test/", minute_ms=2_000)  # type: ignore[arg-type]
    assert not reading.visible, reading.summary()


def test_a_page_that_never_goes_quiet_is_not_confirmed() -> None:
    with pytest.raises(RequestBudgetUnknown, match="NOT CONFIRMED"):
        measure_request_budget(_NeverQuietPage(), "https://app.test/", minute_ms=2_000)  # type: ignore[arg-type]


def test_a_late_read_of_the_visible_minute_is_not_hidden() -> None:
    reading = measure_request_budget(_LateChainPage(), "https://app.test/", minute_ms=2_000)  # type: ignore[arg-type]
    assert reading.visible == {"/api/chained": 1}, reading.summary()
    assert not reading.hidden, reading.summary()
