"""Unit tests for src/logger.py — namespacing + the in-memory ring buffer."""

from __future__ import annotations

from src import clear_log_buffer, get_log_buffer, get_logger


def test_get_logger_namespaces_under_app() -> None:
    assert get_logger("app").name == "app"
    assert get_logger("my_pipeline").name == "app.my_pipeline"


def test_ring_buffer_captures_then_clears() -> None:
    clear_log_buffer()
    get_logger("ring_test").info("hello-ring-buffer-marker")
    buffer = get_log_buffer()
    assert any("hello-ring-buffer-marker" in line for line in buffer)

    clear_log_buffer()
    assert get_log_buffer() == []


def test_debug_lines_stay_below_the_buffer_threshold() -> None:
    # The memory handler is INFO-level; DEBUG lines must not reach the buffer.
    clear_log_buffer()
    get_logger("ring_test").debug("debug-should-not-appear")
    assert not any("debug-should-not-appear" in line for line in get_log_buffer())
