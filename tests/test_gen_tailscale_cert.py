"""`--check` runs before a webapp binds its port, so it must never hang startup.

Two layers: a structural check that every subprocess call in a startup-path script
carries a timeout (the class of defect, caught for the next such script too), and a
behavioural one that a stalled `tailscale cert` leaves the existing cert in place.
"""

from __future__ import annotations

import ast
import datetime
import subprocess
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from scripts import gen_tailscale_cert as gtc
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Scripts an app's launcher runs before binding its port; a hang here is a hung app.
STARTUP_PATH_SCRIPTS = ("scripts/gen_tailscale_cert.py",)
SUBPROCESS_CALLS = frozenset({"run", "check_output", "check_call", "call"})


def untimed_subprocess_calls(rel: str) -> list[int]:
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr in SUBPROCESS_CALLS
        and not any(kw.arg == "timeout" for kw in node.keywords)
    ]


@pytest.mark.parametrize("rel", STARTUP_PATH_SCRIPTS)
def test_every_subprocess_call_on_the_startup_path_has_a_timeout(rel: str) -> None:
    assert untimed_subprocess_calls(rel) == []


def write_expiring_tailnet_cert(cert_dir: Path) -> Path:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "box.tail1234.ts.net")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=80))
        .not_valid_after(now + datetime.timedelta(days=5))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("box.tail1234.ts.net")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    path = cert_dir / "cert.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def test_a_stalled_tailscale_cert_leaves_the_existing_cert_and_startup_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cert_path = write_expiring_tailnet_cert(tmp_path)
    before = cert_path.read_bytes()
    seen: list[object] = []

    def stalled(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(cmd="tailscale cert", timeout=gtc.TAILSCALE_TIMEOUT_S)

    monkeypatch.setattr(gtc, "CERT_DIR", tmp_path)
    monkeypatch.setattr(gtc.shutil, "which", lambda _name: "tailscale")
    monkeypatch.setattr(gtc.subprocess, "run", stalled)

    gtc._check_and_renew()  # must return, not raise

    out = capsys.readouterr().out
    assert seen == [gtc.TAILSCALE_TIMEOUT_S]
    assert "[WARN] Cert renewal failed: tailscale cert timed out" in out
    assert cert_path.read_bytes() == before


def test_a_stalled_tailscale_status_is_a_clear_exit_not_a_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    def stalled(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="tailscale status", timeout=gtc.TAILSCALE_TIMEOUT_S)

    monkeypatch.setattr(gtc.subprocess, "run", stalled)
    with pytest.raises(SystemExit, match="tailscale status timed out"):
        gtc._tailscale_hostname()


def test_the_folder_the_script_writes_the_private_key_into_is_gitignored() -> None:
    key = (gtc.CERT_DIR / "key.pem").relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "check-ignore", "-q", key], cwd=REPO_ROOT, capture_output=True, creationflags=NO_WINDOW, timeout=30
    )
    assert result.returncode == 0, f"{key} is not gitignored: a cloned app would show its private key as committable"
