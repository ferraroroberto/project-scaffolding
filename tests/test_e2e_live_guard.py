from __future__ import annotations

import socket

import pytest

from tests.e2e import _e2e_live_guard as guard


def _reserve_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_free_port_boots_fresh_without_raising(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SCAFFOLD_TEST_E2E_LIVE", raising=False)
    port = _reserve_free_port()

    live_opt_in = guard.require_disposable_instance(port, "SCAFFOLD_TEST_E2E_LIVE")

    assert live_opt_in is False
    assert "booting disposable instance" in capsys.readouterr().out


def test_occupied_port_without_flag_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCAFFOLD_TEST_E2E_LIVE", raising=False)
    port = _reserve_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)

        with pytest.raises(pytest.exit.Exception, match="SCAFFOLD_TEST_E2E_LIVE"):
            guard.require_disposable_instance(port, "SCAFFOLD_TEST_E2E_LIVE")


def test_occupied_port_with_flag_reclaims_without_raising(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SCAFFOLD_TEST_E2E_LIVE", "1")
    port = _reserve_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)

        live_opt_in = guard.require_disposable_instance(port, "SCAFFOLD_TEST_E2E_LIVE")

    assert live_opt_in is True
    assert "reclaiming" in capsys.readouterr().out


def test_port_is_in_use_reflects_a_bound_listener() -> None:
    port = _reserve_free_port()
    assert guard.port_is_in_use(port) is False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)

        assert guard.port_is_in_use(port) is True
