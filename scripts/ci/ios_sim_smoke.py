"""iOS Simulator Mobile Safari smoke of one web-app adopter (macOS only).

The nightly Mac workflow (`.github/workflows/nightly-mac.yml`) runs this once
per adopter after the adopter's WebKit e2e suite. It boots the adopter's own
throwaway instance, opens each key view in real Mobile Safari on an iPhone
simulator and saves one screenshot per view. Playwright's WebKit is close to
Safari but is not Safari; this is the one place the fleet's pages render in
the engine and shell the owner's iPhone actually runs.

The instance comes from the adopter's `.fleet.toml`
`[design.review.synthetic] command`: the fleet's contract for "a disposable,
engine-off copy of this app on a free loopback port". It prints `URL=<base>`
once it answers and tears itself down when its stdin closes. The simulator
shares the Mac's loopback interface, so that URL opens as-is.

Screenshots go to `--out`, a folder outside the checkout on the runner host.
They never enter the repo or an Actions artifact: the workflow runs on a
public repo, and a rendered page can show what a stub could not hide.

Exit codes and the last stdout line:
  0  SMOKE=pass shots=<n>
  1  SMOKE=fail reason=<why>      a view did not produce a screenshot
  3  SMOKE=unknown reason=<why>   could not establish a result (no simctl,
                                  no iPhone simulator, no synthetic command,
                                  the instance never printed its URL)

Usage (from the workflow, with the adopter's venv python):
  python scripts/ci/ios_sim_smoke.py --repo <checkout> --python <venv python> \
      --out <results dir> --view / --view /settings
"""

from __future__ import annotations

import argparse
import json
import logging
import queue
import re
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # a script's own dir is sys.path[0], not the repo root

from src import runtime_files  # noqa: E402 -- needs the sys.path line above

logger =logging.getLogger("ios_sim_smoke")

#: A first boot of a fresh simulator runtime can take minutes (data migration).
BOOT_TIMEOUT_S = 600.0
#: One simctl verb (openurl, screenshot, shutdown) answers in seconds; a hang is a wedge.
SIMCTL_TIMEOUT_S = 120.0
#: simctl's `openurl` can time out (POSIX 60) right after `bootstatus -b` returns; one more try clears it.
OPENURL_ATTEMPTS = 2
OPENURL_RETRY_DELAY_S = 5.0
#: Safari's first launch on a fresh device shows a sheet before the page paints.
DEFAULT_SETTLE_S = 8.0
#: The synthetic command's own default when the adopter declares none.
DEFAULT_STARTUP_S = 60.0
#: A real iPhone screenshot is hundreds of KB; a few bytes means simctl wrote nothing usable.
MIN_SHOT_BYTES = 10_000

_RUNTIME_VERSION = re.compile(r"iOS-(\d+)-(\d+)(?:-(\d+))?$")


class SmokeUnknown(Exception):
    """A prerequisite is missing, so the smoke cannot say pass or fail."""


def pick_device(simctl_json: dict[str, Any]) -> tuple[str, str] | None:
    """The (udid, name) of an available iPhone on the newest iOS runtime.

    `simctl list devices available -j` keys devices by runtime id such as
    `com.apple.CoreSimulator.SimRuntime.iOS-18-2`. An already-booted iPhone on
    that runtime wins, so a rerun reuses it instead of booting a second one.
    """
    best: tuple[tuple[int, ...], int, str, str] | None = None
    for runtime, devices in (simctl_json.get("devices") or {}).items():
        match = _RUNTIME_VERSION.search(runtime)
        if not match:
            continue
        version = tuple(int(p) for p in match.groups() if p is not None)
        for dev in devices or []:
            name = str(dev.get("name", ""))
            if not name.startswith("iPhone") or dev.get("isAvailable") is False:
                continue
            booted = 1 if dev.get("state") == "Booted" else 0
            key = (version, booted, name, str(dev.get("udid", "")))
            if best is None or key[:2] > best[:2]:
                best = key
    return (best[3], best[2]) if best else None


def view_slug(view: str) -> str:
    """A filename-safe name for a view path: `/` is `home`, `/a/b` is `a-b`."""
    slug = re.sub(r"[^a-z0-9]+", "-", view.lower()).strip("-")
    return slug or "home"


def synthetic_command(repo: Path) -> tuple[list[str], float]:
    """The adopter's declared throwaway-instance command and its startup budget."""
    fleet = repo / ".fleet.toml"
    if not fleet.is_file():
        raise SmokeUnknown("adopter has no .fleet.toml")
    with fleet.open("rb") as fh:
        data = tomllib.load(fh)
    synth = data.get("design", {}).get("review", {}).get("synthetic", {})
    command = synth.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
        raise SmokeUnknown("adopter declares no [design.review.synthetic] command")
    return list(command), float(synth.get("startup_timeout_s", DEFAULT_STARTUP_S))


def _simctl(*args: str, timeout: float = SIMCTL_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    # no-window-exempt: macOS-only script; CREATE_NO_WINDOW exists only on Windows
    return subprocess.run(
        ["xcrun", "simctl", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def _read_url(stream: IO[str], timeout: float) -> str | None:
    """The `URL=` line from the instance's stdout, or None after `timeout` seconds."""
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        for line in stream:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=left)
        except queue.Empty:
            return None
        if line is None:
            return None
        if line.startswith("URL="):
            return line[len("URL="):].strip()
    return None


def _boot(udid: str) -> None:
    result = _simctl("boot", udid)
    if result.returncode != 0 and "Booted" not in result.stderr:
        raise SmokeUnknown(f"simctl boot failed: {result.stderr.strip()[:200]}")
    status = _simctl("bootstatus", udid, "-b", timeout=BOOT_TIMEOUT_S)
    if status.returncode != 0:
        raise SmokeUnknown(f"simulator never finished booting: {status.stderr.strip()[:200]}")


def _open_url(udid: str, url: str, view: str) -> bool:
    """Hand `url` to Mobile Safari; one retry absorbs simctl's timeout on a just-booted device.

    A second failure is a real failure and is returned as such, never folded into a pass.
    """
    for attempt in range(1, OPENURL_ATTEMPTS + 1):
        opened = _simctl("openurl", udid, url)
        if opened.returncode == 0:
            logger.info("ℹ️ openurl %s ok (attempt %d/%d)", view, attempt, OPENURL_ATTEMPTS)
            return True
        logger.warning(
            "⚠️ openurl failed for %s (attempt %d/%d): %s",
            view, attempt, OPENURL_ATTEMPTS, opened.stderr.strip()[:200],
        )
        if attempt < OPENURL_ATTEMPTS:
            time.sleep(OPENURL_RETRY_DELAY_S)
    return False


def _shoot(udid: str, base: str, views: Sequence[str], out: Path, settle_s: float) -> list[str]:
    """Open each view and screenshot it; returns the views that produced no usable image."""
    missing: list[str] = []
    for view in views:
        url = base.rstrip("/") + (view if view.startswith("/") else "/" + view)
        target = out / f"{view_slug(view)}.png"
        if not _open_url(udid, url, view):
            missing.append(view)
            continue
        time.sleep(settle_s)
        shot = _simctl("io", udid, "screenshot", str(target))
        size = target.stat().st_size if target.is_file() else 0
        if shot.returncode != 0 or size < MIN_SHOT_BYTES:
            logger.warning("⚠️ no usable screenshot for %s (%d bytes)", view, size)
            missing.append(view)
            continue
        logger.info("✅ %s -> %s (%d KB)", view, target.name, size // 1024)
    return missing


def run(repo: Path, python: str, views: Sequence[str], out: Path, settle_s: float) -> tuple[int, str]:
    """Boot the instance, shoot every view, tear down; returns (exit code, result line)."""
    try:
        command, startup_s = synthetic_command(repo)
        listing = _simctl("list", "devices", "available", "-j")
        if listing.returncode != 0:
            raise SmokeUnknown("xcrun simctl is unavailable (Xcode not installed or not selected)")
        device = pick_device(json.loads(listing.stdout))
        if device is None:
            raise SmokeUnknown("no available iPhone simulator (xcodebuild -downloadPlatform iOS)")
    except (SmokeUnknown, FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return 3, f"SMOKE=unknown reason={exc}"

    udid, name = device
    logger.info("ℹ️ device: %s", name)
    runtime_files.make_dirs(out)
    # no-window-exempt: macOS-only script; CREATE_NO_WINDOW exists only on Windows
    instance = subprocess.Popen(
        [python, *command], cwd=str(repo), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    try:
        base = _read_url(instance.stdout, startup_s) if instance.stdout else None
        if not base:
            return 3, f"SMOKE=unknown reason=instance printed no URL= within {startup_s:.0f}s"
        logger.info("ℹ️ instance ready on loopback")
        _boot(udid)
        missing = _shoot(udid, base, views, out, settle_s)
    except SmokeUnknown as exc:
        return 3, f"SMOKE=unknown reason={exc}"
    except subprocess.TimeoutExpired as exc:
        return 3, f"SMOKE=unknown reason=simctl timed out: {' '.join(map(str, exc.cmd[2:4]))}"
    finally:
        if instance.stdin:
            instance.stdin.close()
        try:
            instance.wait(timeout=30)
        except subprocess.TimeoutExpired:
            instance.kill()
            instance.wait(timeout=10)
        _simctl("shutdown", udid)

    shots = len(views) - len(missing)
    if missing:
        return 1, f"SMOKE=fail reason=no screenshot for {', '.join(missing)} shots={shots}"
    return 0, f"SMOKE=pass shots={shots}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, type=Path, help="the adopter's checkout")
    parser.add_argument("--python", required=True, help="the adopter's venv python")
    parser.add_argument("--out", required=True, type=Path, help="screenshot folder, outside the checkout")
    parser.add_argument("--view", action="append", default=[], help="a view path; repeatable (default /)")
    parser.add_argument("--settle-s", type=float, default=DEFAULT_SETTLE_S)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if sys.platform != "darwin":
        print("SMOKE=unknown reason=the iOS Simulator runs only on macOS")
        return 3
    code, line = run(args.repo.resolve(), args.python, args.view or ["/"], args.out, args.settle_s)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
