from __future__ import annotations

import subprocess

import pytest

from tests import _streamlit_lifecycle as lifecycle


def test_ensure_fresh_streamlit_fails_when_port_stays_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed_ports: list[int] = []

    def fake_kill_streamlit_on_port(port: int) -> None:
        killed_ports.append(port)

    def fake_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        raise AssertionError("should not spawn Streamlit while the port is bound")

    monkeypatch.setattr(lifecycle, "port_is_in_use", lambda port: True)
    monkeypatch.setattr(lifecycle, "kill_streamlit_on_port", fake_kill_streamlit_on_port)
    monkeypatch.setattr(lifecycle, "_wait_until", lambda predicate, timeout: False)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError, match="still in use"):
        lifecycle.ensure_fresh_streamlit(port=9999)

    assert killed_ports == [9999]
