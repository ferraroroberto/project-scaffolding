"""Thread, handle and RSS counts for a process, plus the runtime breadcrumb.

A long-lived webapp that leaks a thread or a handle per request looks healthy
until the machine runs out of both, so the counts must be readable twice over:
by the gate (``tests/soak/_resource_soak.py`` samples the app it booted before and
after a burst of its own poll routes) and by the running app itself
(:func:`start_breadcrumb` logs them on a fixed interval, so a leak found in
production is diagnosable from the log).

**A sample it cannot take is :class:`SampleUnavailable`, never a zero.** A
caller that treated "could not read" as "nothing leaked" would pass the very
state this module exists to catch.

Counts cover the process and, by default, its descendants: on Windows a venv
``python.exe`` is a launcher that re-executes the real interpreter as a child,
so the pid a harness holds is not the process serving the port.

Vendor-verbatim: consuming apps copy this file byte-identical into their own
``src/`` (like ``src/build_info.py``). Stdlib only; Windows through ``ctypes``,
Linux through ``/proc``, anything else is unavailable.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


class SampleUnavailable(Exception):
    """The counts could not be read; the reason is the message."""


@dataclass(frozen=True)
class ResourceSample:
    threads: int
    handles: int
    rss_bytes: int
    processes: int


def format_sample(sample: ResourceSample) -> str:
    """The breadcrumb body: ``threads=12 handles=340 rss=85.3MB``."""
    return f"threads={sample.threads} handles={sample.handles} rss={sample.rss_bytes / 1048576:.1f}MB"


def _descendants(root: int, parent_of: dict[int, int]) -> list[int]:
    """``root`` plus every process below it, given a pid -> parent-pid map."""
    children: dict[int, list[int]] = {}
    for pid, ppid in parent_of.items():
        children.setdefault(ppid, []).append(pid)
    found, queue = [root], [root]
    while queue:
        for child in children.get(queue.pop(), []):
            if child not in found:
                found.append(child)
                queue.append(child)
    return found


def _sample_linux(pid: int, include_children: bool, proc: Path = Path("/proc")) -> ResourceSample:
    parent_of: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            # The command name sits in parentheses and may contain spaces.
            parent_of[int(entry.name)] = int(stat[stat.rindex(")") + 2 :].split()[1])
        except (OSError, ValueError, IndexError):
            continue  # exited between the listing and the read
    if pid not in parent_of:
        raise SampleUnavailable(f"process {pid} is not running")
    pids = _descendants(pid, parent_of) if include_children else [pid]
    threads = handles = rss = 0
    for one in pids:
        try:
            status = (proc / str(one) / "status").read_text(encoding="utf-8", errors="replace")
            fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
            threads += int(fields["Threads"].strip())
            rss += int(fields.get("VmRSS", "0 kB").split()[0]) * 1024
            handles += sum(1 for _ in (proc / str(one) / "fd").iterdir())
        except (OSError, KeyError, ValueError) as exc:
            raise SampleUnavailable(f"cannot read /proc/{one}: {exc}") from exc
    return ResourceSample(threads, handles, rss, len(pids))


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _TH32CS_SNAPPROCESS = 0x2
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ERROR_INVALID_PARAMETER = 87  # OpenProcess on a pid that has just exited

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class _MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    def _kernel32() -> ctypes.WinDLL:
        # Declared per call: argtypes/restype stop 64-bit handles being truncated.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MemoryCounters), wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        return k32

    def _process_table(k32: ctypes.WinDLL) -> dict[int, tuple[int, int]]:
        """pid -> (parent pid, thread count) for every running process."""
        snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snap is None or snap == wintypes.HANDLE(-1).value:
            raise SampleUnavailable(f"process snapshot failed (error {ctypes.get_last_error()})")
        table: dict[int, tuple[int, int]] = {}
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(_ProcessEntry)
            more = k32.Process32FirstW(snap, ctypes.byref(entry))
            while more:
                table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.cntThreads)
                more = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return table

    def _sample_windows(pid: int, include_children: bool) -> ResourceSample:
        k32 = _kernel32()
        table = _process_table(k32)
        if pid not in table:
            raise SampleUnavailable(f"process {pid} is not running")
        pids = _descendants(pid, {p: parent for p, (parent, _) in table.items()}) if include_children else [pid]
        threads = handles = rss = 0
        for one in pids:
            proc = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, one)
            if not proc:
                if one != pid and ctypes.get_last_error() == _ERROR_INVALID_PARAMETER:
                    continue
                raise SampleUnavailable(f"cannot open process {one} (error {ctypes.get_last_error()})")
            try:
                count = wintypes.DWORD()
                memory = _MemoryCounters()
                memory.cb = ctypes.sizeof(_MemoryCounters)
                if not k32.GetProcessHandleCount(proc, ctypes.byref(count)):
                    raise SampleUnavailable(f"handle count of process {one} failed (error {ctypes.get_last_error()})")
                if not k32.K32GetProcessMemoryInfo(proc, ctypes.byref(memory), memory.cb):
                    raise SampleUnavailable(f"memory info of process {one} failed (error {ctypes.get_last_error()})")
            finally:
                k32.CloseHandle(proc)
            threads += table[one][1]
            handles += count.value
            rss += memory.WorkingSetSize
        return ResourceSample(threads, handles, rss, len(pids))


def sample_process(pid: int | None = None, *, include_children: bool = True) -> ResourceSample:
    """Counts for ``pid`` (this process when ``None``) and, by default, its descendants."""
    target = os.getpid() if pid is None else pid
    if sys.platform == "win32":
        return _sample_windows(target, include_children)
    if sys.platform.startswith("linux"):
        return _sample_linux(target, include_children)
    raise SampleUnavailable(f"no resource sampler for platform {sys.platform}")


def start_breadcrumb(logger: logging.Logger, interval_seconds: float = 300.0) -> threading.Event:
    """Log this process's counts now and then every ``interval_seconds``.

    Returns the stop event. One unreadable sample logs a single warning and ends
    the loop: a breadcrumb that cannot be taken must say so once, not every tick.
    """
    stop = threading.Event()

    def run() -> None:
        while True:
            try:
                sample = sample_process(include_children=False)
            except SampleUnavailable as exc:
                logger.warning("⚠️ resource breadcrumb unavailable: %s", exc)
                return
            logger.info("ℹ️ resources %s", format_sample(sample))
            if stop.wait(interval_seconds):
                return

    threading.Thread(target=run, name="resource-breadcrumb", daemon=True).start()
    return stop
