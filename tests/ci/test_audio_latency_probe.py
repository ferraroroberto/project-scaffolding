"""`scripts/ci/audio_latency_probe.py`: the verdict logic that decides whether a nightly run hurts STT.

The probe's network half needs the live hub; these cover what turns two sets of
samples into a verdict: the percentile, the window filter, and that anything
unestablished (errors, too few samples, different serving hosts) reports
`unknown` (exit 3), never a pass.
"""

from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import audio_latency_probe as probe  # noqa: E402 -- needs the sys.path line above


def _samples(latencies: list[float], host: str = "h1", model: str = "m1", status: int = 200, t0: float = 0.0):
    return [
        {"t": t0 + i, "ms": ms, "status": status, "served_host": host, "served_model": model}
        for i, ms in enumerate(latencies)
    ]


def _summary(latencies: list[float], **kw):
    return probe.summarize(_samples(latencies, **kw))


def test_percentile_is_nearest_rank() -> None:
    values = list(range(1, 101))
    assert probe.percentile(values, 95) == 95
    assert probe.percentile([5.0], 95) == 5.0


def test_wav_is_a_valid_mono_16bit_clip() -> None:
    with wave.open(io.BytesIO(probe.build_wav(1.0)), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, probe.CLIP_RATE)
        assert w.getnframes() == probe.CLIP_RATE


def test_multipart_carries_fields_and_file() -> None:
    body, content_type = probe.build_multipart({"model": "x"}, "a.wav", b"RIFF")
    boundary = content_type.split("boundary=")[1].encode()
    assert b'name="model"\r\n\r\nx' in body
    assert b'filename="a.wav"' in body and b"RIFF" in body
    assert body.endswith(b"--" + boundary + b"--\r\n")


def test_window_filter_is_inclusive_and_open_ended() -> None:
    s = _samples([1, 2, 3, 4])
    assert [x["ms"] for x in probe.select_window(s, 1, 2)] == [2, 3]
    assert len(probe.select_window(s, None, None)) == 4


def test_equal_windows_are_negligible() -> None:
    code, line = probe.judge(_summary([100.0] * 30), _summary([100.0] * 30))
    assert code == 0 and line.startswith("IMPACT=negligible")


def test_within_relative_plus_margin_is_negligible() -> None:
    # 1000 ms baseline p95: bound is 1000 * 1.10 + 150 = 1250.
    code, _ = probe.judge(_summary([1000.0] * 30), _summary([1250.0] * 30))
    assert code == 0


def test_above_the_bound_is_material() -> None:
    code, line = probe.judge(_summary([1000.0] * 30), _summary([1251.0] * 30))
    assert code == 1 and line.startswith("IMPACT=material")


def test_failed_requests_are_unknown_not_fast() -> None:
    during = probe.summarize(_samples([100.0] * 30) + _samples([5.0], status=0))
    code, line = probe.judge(_summary([100.0] * 30), during)
    assert code == 3 and "failed request" in line


def test_too_few_samples_is_unknown() -> None:
    code, line = probe.judge(_summary([100.0] * 30), _summary([100.0] * 5))
    assert code == 3 and "need" in line


def test_different_serving_host_is_unknown() -> None:
    code, line = probe.judge(_summary([100.0] * 30), _summary([100.0] * 30, host="h2"))
    assert code == 3 and "different hosts" in line


def test_unreported_host_is_unknown() -> None:
    code, line = probe.judge(_summary([100.0] * 30, host=""), _summary([100.0] * 30, host=""))
    assert code == 3 and "did not report" in line


def test_compare_with_unreadable_file_is_unknown(tmp_path: Path, capsys) -> None:
    code = probe.main(["compare", str(tmp_path / "missing.json"), str(tmp_path / "missing2.json")])
    assert code == 3
    assert capsys.readouterr().out.strip().startswith("IMPACT=unknown")
