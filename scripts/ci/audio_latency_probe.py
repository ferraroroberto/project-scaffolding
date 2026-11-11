"""Speech-to-text latency of the hub's audio route, before and during a nightly run.

The Mac Mini that hosts the nightly runner also serves speech-to-text for the
hub (the `audio_transcribe` role). This answers one question: does a
`nightly-mac` run move that latency? The same fixed probe runs twice, once with
the Mac idle and once overlapping a run, and the two p95 figures are compared.

Everything goes through the hub's audio route (`/v1/audio/transcriptions`), so
the hub decides which host serves it and the probe never addresses a backend
port, a host or a key. Each response's `X-Hub-Served-Host` / `X-Hub-Served-Model`
headers are recorded, and a comparison whose two windows were served by
different hosts or models is `unknown`, never a pass.

The clip is a synthetic tone, so no recording of the owner is involved. What is
measured is request round trip, not transcript quality.

Subcommands:
  probe     send `--count` clips, `--interval-s` apart, and write the samples as
            JSON to `--out`.
  compare   read two sample files and end with one line:
              IMPACT=negligible   during p95 <= baseline p95 * (1 + rel) + margin
              IMPACT=material     above that bound
              IMPACT=unknown      too few good samples, errors, or the two
                                  windows were served by different hosts or models
            exit 0 / 1 / 3 respectively.

Usage:
  python scripts/ci/audio_latency_probe.py probe --label baseline --out baseline.json
  python scripts/ci/audio_latency_probe.py probe --label during --out during.json
  python scripts/ci/audio_latency_probe.py compare baseline.json during.json \
      [--from T --to T]   # restrict the during window to a unix-time range
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import logging
import math
import struct
import sys
import time
import uuid
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # a script's own dir is sys.path[0], not the repo root

from src import runtime_files  # noqa: E402 -- needs the sys.path line above

logger =logging.getLogger("audio_latency_probe")

DEFAULT_HUB = "http://127.0.0.1:8000"
#: The hub's transcribe role: parakeet on the Mac with whisper as the fallback.
DEFAULT_MODEL = "audio_transcribe"
#: A nearest-rank p95 of fewer than 20 samples is just the maximum.
MIN_SAMPLES = 20
#: "Negligible" is up to +10% at p95 plus a small fixed margin for timer noise.
DEFAULT_REL = 0.10
DEFAULT_MARGIN_MS = 150.0
#: One transcription of a few seconds of audio answers in well under a minute.
REQUEST_TIMEOUT_S = 60.0
CLIP_SECONDS = 4.0
CLIP_RATE = 16_000


def build_wav(seconds: float = CLIP_SECONDS, rate: int = CLIP_RATE) -> bytes:
    """A mono 16-bit WAV: a quiet tone under slow amplitude modulation.

    Pure silence can be short-circuited by a voice-activity filter and would
    measure nothing; a modulated tone always reaches the decoder.
    """
    frames = bytearray()
    for i in range(int(seconds * rate)):
        t = i / rate
        envelope = 0.5 + 0.5 * math.sin(2 * math.pi * 1.5 * t)
        value = int(6000 * envelope * math.sin(2 * math.pi * 220 * t))
        frames += struct.pack("<h", value)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def build_multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
    """A multipart/form-data body (stdlib has none) and its Content-Type."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile; the caller guarantees `values` is not empty."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def select_window(samples: list[dict[str, Any]], start: float | None, end: float | None) -> list[dict[str, Any]]:
    """Samples whose send time `t` falls in [start, end]; a missing bound is open."""
    return [
        s for s in samples
        if (start is None or s["t"] >= start) and (end is None or s["t"] <= end)
    ]


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts, latency figures over the 2xx samples, and who served them."""
    good = [s["ms"] for s in samples if 200 <= s.get("status", 0) < 300]
    summary: dict[str, Any] = {
        "sent": len(samples),
        "ok": len(good),
        "errors": len(samples) - len(good),
        "hosts": sorted({s.get("served_host", "") for s in samples}),
        "models": sorted({s.get("served_model", "") for s in samples}),
    }
    if good:
        summary.update(
            p50_ms=round(percentile(good, 50), 1),
            p95_ms=round(percentile(good, 95), 1),
            max_ms=round(max(good), 1),
        )
    return summary


def judge(
    baseline: dict[str, Any],
    during: dict[str, Any],
    rel: float = DEFAULT_REL,
    margin_ms: float = DEFAULT_MARGIN_MS,
    min_samples: int = MIN_SAMPLES,
) -> tuple[int, str]:
    """(exit code, last line) for two summaries. Anything unestablished is unknown."""
    for name, s in (("baseline", baseline), ("during", during)):
        if s["errors"]:
            return 3, f"IMPACT=unknown reason={name} window had {s['errors']} failed request(s)"
        if s["ok"] < min_samples:
            return 3, f"IMPACT=unknown reason={name} window has {s['ok']} samples, need {min_samples}"
    if baseline["hosts"] != during["hosts"] or baseline["models"] != during["models"]:
        return 3, "IMPACT=unknown reason=the two windows were served by different hosts or models"
    if "" in baseline["hosts"] or "" in baseline["models"]:
        return 3, "IMPACT=unknown reason=the hub did not report which host and model served"
    bound = baseline["p95_ms"] * (1 + rel) + margin_ms
    figures = f"baseline_p95_ms={baseline['p95_ms']} during_p95_ms={during['p95_ms']} bound_ms={round(bound, 1)}"
    if during["p95_ms"] <= bound:
        return 0, f"IMPACT=negligible {figures}"
    return 1, f"IMPACT=material {figures}"


def _send(conn: http.client.HTTPConnection, path: str, body: bytes, content_type: str) -> http.client.HTTPResponse:
    conn.request("POST", path, body=body, headers={"Content-Type": content_type})
    resp = conn.getresponse()
    resp.read()
    return resp


def _post_once(conn: http.client.HTTPConnection, path: str, model: str, wav: bytes) -> dict[str, Any]:
    body, content_type = build_multipart({"model": model, "response_format": "json"}, "probe.wav", wav)
    sent_at = time.time()
    started = time.perf_counter()
    try:
        try:
            resp = _send(conn, path, body, content_type)
        except (ConnectionError, http.client.RemoteDisconnected):
            # The server closes an idle keep-alive connection after a few
            # seconds; the clip spacing is longer than that. Reopen once and
            # time the request that actually reaches the hub.
            conn.close()
            started = time.perf_counter()
            resp = _send(conn, path, body, content_type)
        status = resp.status
        headers = {k.lower(): v for k, v in resp.getheaders()}
    except (OSError, http.client.HTTPException) as exc:
        conn.close()
        logger.warning("⚠️ request failed: %s", type(exc).__name__)
        return {"t": sent_at, "ms": (time.perf_counter() - started) * 1000, "status": 0}
    return {
        "t": sent_at,
        "ms": (time.perf_counter() - started) * 1000,
        "status": status,
        "served_host": headers.get("x-hub-served-host", ""),
        "served_model": headers.get("x-hub-served-model", ""),
    }


def run_probe(hub: str, model: str, count: int, interval_s: float) -> list[dict[str, Any]]:
    """Send `count` clips over one kept-alive connection, `interval_s` apart."""
    parts = urlsplit(hub)
    if parts.scheme != "http" or not parts.hostname:
        raise SystemExit("--hub must be an http:// URL")
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=REQUEST_TIMEOUT_S)
    wav = build_wav()
    samples: list[dict[str, Any]] = []
    try:
        for i in range(count):
            samples.append(_post_once(conn, "/v1/audio/transcriptions", model, wav))
            if i + 1 < count:
                time.sleep(interval_s)
    finally:
        conn.close()
    return samples


def _cmd_probe(args: argparse.Namespace) -> int:
    samples = run_probe(args.hub, args.model, args.count, args.interval_s)
    payload = {"label": args.label, "model": args.model, "samples": samples}
    runtime_files.save_text(args.out, json.dumps(payload))
    summary = summarize(samples)
    logger.info("ℹ️ %s: %s", args.label, json.dumps(summary))
    print(f"PROBE={args.label} sent={summary['sent']} ok={summary['ok']} errors={summary['errors']}")
    return 0 if summary["ok"] else 3


def _load(path: Path, start: float | None = None, end: float | None = None) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return summarize(select_window(data["samples"], start, end))


def _cmd_compare(args: argparse.Namespace) -> int:
    try:
        baseline = _load(args.baseline)
        during = _load(args.during, args.window_from, args.window_to)
    except (OSError, ValueError, KeyError) as exc:
        print(f"IMPACT=unknown reason=cannot read samples ({type(exc).__name__})")
        return 3
    logger.info("ℹ️ baseline: %s", json.dumps(baseline))
    logger.info("ℹ️ during:   %s", json.dumps(during))
    code, line = judge(baseline, during, args.rel, args.margin_ms, args.min_samples)
    print(line)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="send clips to the hub and record latencies")
    probe.add_argument("--label", required=True)
    probe.add_argument("--out", required=True, type=Path)
    probe.add_argument("--hub", default=DEFAULT_HUB)
    probe.add_argument("--model", default=DEFAULT_MODEL)
    probe.add_argument("--count", type=int, default=40)
    probe.add_argument("--interval-s", type=float, default=5.0)
    probe.set_defaults(func=_cmd_probe)

    compare = sub.add_parser("compare", help="judge a during-run window against a baseline")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("during", type=Path)
    compare.add_argument("--from", dest="window_from", type=float, default=None)
    compare.add_argument("--to", dest="window_to", type=float, default=None)
    compare.add_argument("--rel", type=float, default=DEFAULT_REL)
    compare.add_argument("--margin-ms", type=float, default=DEFAULT_MARGIN_MS)
    compare.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    compare.set_defaults(func=_cmd_compare)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
