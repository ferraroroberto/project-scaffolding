"""Shared plumbing for test_tray_lifecycle_behavior.py.

Builds a throwaway "app repo" per test: a stub venv (just the redirect
launcher stubs + pyvenv.cfg, copied from this repo's own real .venv -- see
`make_stub_venv`), a one-commit git repo (the version-verify leg needs a real
`git rev-parse HEAD`), a `tray.bat` materialized from the real
`tray.bat.template`, and the REAL `app/tray/tray_lifecycle.ps1` vendored in
byte-for-byte (never a stub or a mock). Everything here drives real
subprocesses; nothing simulates tray_lifecycle.ps1's own logic.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[2]
DUMMY_APP = _HERE.parent / "_dummy_tray_app.py"
REAL_VENV = ROOT / ".venv"
TRAY_LIFECYCLE_SRC = ROOT / "app" / "tray" / "tray_lifecycle.ps1"
TRAY_BAT_TEMPLATE = ROOT / "tray.bat.template"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass
class TrayEnv:
    script_dir: Path
    venv_dir: Path
    tray_bat: Path
    port: int
    tray_match: str
    https: bool


# ---------------------------------------------------------------------------
# git (the version-verify leg needs a real HEAD to compare against)
# ---------------------------------------------------------------------------

def _run_git(repo_dir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True, text=True, check=True, creationflags=_NO_WINDOW,
    )
    return result.stdout.strip()


def git_init_with_commit(repo_dir: Path) -> str:
    """Init a throwaway repo with one commit; return its HEAD sha.

    Relies on the machine's global git identity (this box's pre-commit hook
    enforces an author-email allowlist even on a brand-new repo, so a fake
    `-c user.email=...` override is rejected -- the global identity is
    already allowlisted).
    """
    repo_dir.mkdir(parents=True, exist_ok=True)
    _run_git(repo_dir, "init", "-q")
    _run_git(repo_dir, "commit", "--allow-empty", "-q", "-m", "initial")
    return _run_git(repo_dir, "rev-parse", "HEAD")


def git_commit_allow_empty(repo_dir: Path, message: str) -> str:
    """Bump the repo's build -- the harness's stand-in for shipping a new commit."""
    _run_git(repo_dir, "commit", "--allow-empty", "-q", "-m", message)
    return _run_git(repo_dir, "rev-parse", "HEAD")


def head_sha(repo_dir: Path) -> str:
    return _run_git(repo_dir, "rev-parse", "HEAD")


# ---------------------------------------------------------------------------
# stub venv
# ---------------------------------------------------------------------------

def make_stub_venv(venv_dir: Path) -> None:
    """A minimal PEP-405 venv redirect: just the launcher stubs + pyvenv.cfg,
    copied from this repo's own real `.venv`.

    No `Lib/site-packages` needed -- the dummy app uses only the stdlib + a
    `git` subprocess, and the venv launcher redirects to the base
    interpreter's stdlib regardless. This reproduces the exact "pythoncore"
    venv shape documented in docs/windows-tray.md: a venv-launched
    `pythonw.exe` re-execs the base interpreter, so only the process
    CommandLine -- never the image path -- carries the `.venv` path. That is
    precisely the condition `tray_lifecycle.ps1`'s CommandLine-scoped
    matching (`Test-UnderVenv`) exists for, so stubbing it this way is higher
    fidelity than a from-scratch `python -m venv`, not a shortcut.
    """
    if not (REAL_VENV / "pyvenv.cfg").exists():
        raise RuntimeError(f"expected a real .venv at {REAL_VENV} to stub from")
    scripts = venv_dir / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for exe in ("python.exe", "pythonw.exe"):
        shutil.copy2(REAL_VENV / "Scripts" / exe, scripts / exe)
    shutil.copy2(REAL_VENV / "pyvenv.cfg", venv_dir / "pyvenv.cfg")


# ---------------------------------------------------------------------------
# self-signed loopback cert (the #147/#148 probe bug)
# ---------------------------------------------------------------------------

def generate_self_signed_loopback_cert(cert_path: Path, key_path: Path) -> None:
    """A cert for 127.0.0.1 that no public CA would ever issue -- the same
    shape as a fleet PWA's leaf (Tailscale / self-signed CA, never a
    loopback-named cert), which is exactly why the verify leg needs
    `LoopbackCertBypass` at all.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


# ---------------------------------------------------------------------------
# tray.bat materialization + invocation
# ---------------------------------------------------------------------------

def materialize_tray_bat(
    script_dir: Path, *, app_name: str, tray_launch: str, tray_match: str, owned_port: int,
) -> Path:
    text = TRAY_BAT_TEMPLATE.read_text(encoding="utf-8")
    text = (
        text.replace("__APP_NAME__", app_name)
        .replace("__TRAY_LAUNCH__", tray_launch)
        .replace("__TRAY_MATCH__", tray_match)
        .replace("__OWNED_PORTS__", str(owned_port))
    )
    tray_bat = script_dir / "tray.bat"
    tray_bat.write_text(text, encoding="utf-8")

    helper_dir = script_dir / "app" / "tray"
    helper_dir.mkdir(parents=True, exist_ok=True)
    # The REAL helper, vendored verbatim -- never a stub or a mock. This is
    # the whole point of the harness: drive the actual shipped lifecycle.
    shutil.copy2(TRAY_LIFECYCLE_SRC, helper_dir / "tray_lifecycle.ps1")
    return tray_bat


def run_tray_bat(
    tray_bat: Path, args: list[str], *, nested: bool = False, timeout: float = 90.0,
) -> subprocess.CompletedProcess[str]:
    """Invoke the materialized tray.bat.

    ``nested=True`` reproduces the exact historical failure trigger
    (project-scaffolding#54/#144): a non-interactive nested shell with no
    console/tty attached -- Git Bash -> `cmd /c "tray.bat --restart"`, or an
    agent's Bash tool -- via a closed stdin and CREATE_NO_WINDOW, not merely
    "invoked through cmd".
    """
    cmd = ["cmd", "/c", str(tray_bat), *args]
    kwargs: dict[str, object] = dict(
        cwd=str(tray_bat.parent), capture_output=True, text=True, timeout=timeout,
    )
    if nested:
        kwargs["stdin"] = subprocess.DEVNULL
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)  # type: ignore[call-overload]


# ---------------------------------------------------------------------------
# process introspection / cleanup (drives the REAL helper's own actions)
# ---------------------------------------------------------------------------

def detect_pids(venv_dir: Path, tray_match: str) -> list[str]:
    result = subprocess.run(
        [
            POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(TRAY_LIFECYCLE_SRC), "detect",
            "-VenvDir", str(venv_dir), "-TrayMatch", tray_match,
        ],
        capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]


def wait_for_tray_pids(venv_dir: Path, tray_match: str, timeout: float = 15.0) -> list[str]:
    """Poll `detect` until it returns a stable, non-empty PID set.

    On this box's Python 3.14 "pythoncore" venv shape, a single logical tray
    shows up as TWO PIDs -- the venv launcher stub and the re-exec'd base
    interpreter child it hands off to (docs/windows-tray.md, "the cascade
    caveat") -- both matching TrayMatch/Test-UnderVenv. So "one tray running"
    is not "exactly one PID"; it is one *stable* PID set. Requiring two
    consecutive identical reads is what distinguishes "still spawning" from
    "actually running", and lets the idempotency test compare PID *sets*
    rather than assume a PID count that doesn't hold on this venv shape.
    """
    deadline = time.time() + timeout
    previous: list[str] | None = None
    while time.time() < deadline:
        current = detect_pids(venv_dir, tray_match)
        if current and current == previous:
            return current
        previous = current
        time.sleep(0.5)
    return previous or []


def _listening_pids_on_port(port: int) -> list[str]:
    out = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    ).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            pids.add(parts[4])
    return sorted(pids)


def cleanup_env(env: TrayEnv) -> None:
    """Best-effort teardown so a failed assertion never leaks a process.

    Kills every PID the real helper's own `detect` still finds, reclaims the
    port through the real helper's own `reclaim`, then a direct
    kill-by-port backstop. Safe by construction: the port is always this
    test's own ephemeral port, never a fleet port.
    """
    for pid in detect_pids(env.venv_dir, env.tray_match):
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", pid],
            capture_output=True, creationflags=_NO_WINDOW,
        )
    subprocess.run(
        [
            POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(TRAY_LIFECYCLE_SRC), "reclaim",
            "-VenvDir", str(env.venv_dir), "-Ports", str(env.port),
        ],
        capture_output=True, timeout=20, creationflags=_NO_WINDOW,
    )
    for pid in _listening_pids_on_port(env.port):
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", pid],
            capture_output=True, creationflags=_NO_WINDOW,
        )


# ---------------------------------------------------------------------------
# version-endpoint polling (the Python-side assertion, independent of the
# ps1's own Wait-VersionMatchesHead -- proves the served value from outside)
# ---------------------------------------------------------------------------

def poll_version(port: int, *, https: bool, timeout: float = 30.0) -> dict[str, object]:
    scheme = "https" if https else "http"
    url = f"{scheme}://127.0.0.1:{port}/api/version"
    ctx = ssl._create_unverified_context() if https else None  # noqa: SLF001 -- loopback test-only probe
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3, context=ctx) as resp:  # type: ignore[arg-type]
                return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]
        except Exception as exc:  # noqa: BLE001 -- polling loop, any failure just retries
            last_err = exc
            time.sleep(0.5)
    raise TimeoutError(f"{url} did not respond within {timeout}s: {last_err}")


# ---------------------------------------------------------------------------
# env builder
# ---------------------------------------------------------------------------

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_env(script_dir: Path, *, app_name: str = "ScaffoldE2E", https: bool = False) -> TrayEnv:
    venv_dir = script_dir / ".venv"
    make_stub_venv(venv_dir)
    git_init_with_commit(script_dir)

    port = find_free_port()
    # Scoped by port so leftover dummy processes from an earlier failed run
    # (a different port) are never matched -- the harness only ever touches
    # what it just spawned.
    tray_match = rf"_dummy_tray_app\.py.*--port\s+{port}\b"

    launch_parts = [f'"{DUMMY_APP}"', "--port", str(port)]
    if https:
        cert_path = script_dir / "cert.pem"
        key_path = script_dir / "key.pem"
        generate_self_signed_loopback_cert(cert_path, key_path)
        launch_parts += ["--https", "--cert", f'"{cert_path}"', "--key", f'"{key_path}"']
    tray_launch = " ".join(launch_parts)

    tray_bat = materialize_tray_bat(
        script_dir, app_name=app_name, tray_launch=tray_launch,
        tray_match=tray_match, owned_port=port,
    )
    return TrayEnv(
        script_dir=script_dir, venv_dir=venv_dir, tray_bat=tray_bat,
        port=port, tray_match=tray_match, https=https,
    )
