# Sharing a persistent Chrome profile across jobs (didactic)

Personal reference for projects that drive **real Chrome with a persistent
profile** to automate a site (scraping, posting) — *not* the UI-testing loops
in `playwright-ui-testing.md`. Captures the *mental model* and the *one rule*
that keeps two jobs from corrupting each other's run.

> **Audience.** Me, plus any AI coding agent I hand a project to.
> **Status.** Living reference, not a changelog. Update in place when the
> recipe changes.

---

## TL;DR

- A persistent Chrome profile (`channel="chrome"` + a dedicated
  `user-data-dir`) allows **exactly one live Chrome instance**.
- When two unattended jobs share one profile, the second to launch gets
  Playwright's *"Opening in existing browser session"* error and dies.
- **The rule: serialize by waiting, never by killing.** Wait for the holder
  to finish; do not terminate it.

---

## The mental model

Several jobs in a project often want the same logged-in browser session — a
scrape job and a reporting job both need *my* authenticated LinkedIn. The
cheap way to share that session is to point both at the same
`<platform>/chrome_user_data` profile. The catch: Chrome enforces a single
live instance per profile. Two jobs firing from a scheduler around the same
time race for it, and one loses.

The tempting "fix" is to detect the lock and kill whatever holds the profile,
then retry. **This is wrong.** The holder is almost always the *other
legitimate job*, mid-run. Killing it trades one failed job for two — and can
corrupt the profile the survivor then opens.

The right model is a queue of one: if someone else holds the profile, **wait
your turn**.

## The rule

On a locked-profile launch error:

1. **Detect** whether a live Chrome holds *this exact* profile (match
   `--user-data-dir=<this dir>` on the process command line). Log it — knowing
   *who* holds it is half the debugging.
2. **Wait** with exponential backoff (`60 → 120 → 240 → 480` s, ~15 min
   total), re-attempting the launch after each wait. Return the moment the
   profile frees.
3. **Never kill.** If the profile is *still* held after the full schedule,
   raise a precise error naming the dir and the holder PID(s). A process
   holding the profile that long is genuinely hung — surface it, don't murder
   a (possibly slow but legitimate) sibling.
4. Non-lock launch errors propagate unchanged.

Interactive bootstrap/login flows stay **fail-fast** — a silent 15-minute
wait while I'm trying to log in by hand is just confusing. The wait applies
only to unattended runtime sessions.

## Platform gotcha (Windows)

Chrome's profile lock on Windows is a **live-process kernel object**, not the
POSIX `SingletonLock` / `SingletonCookie` / `SingletonSocket` files. Deleting
those files "to clear a stale lock" does nothing on Windows — the only thing
that releases the profile is the holding process exiting. This is *why* the
remedy is "wait for the process," not "remove the lock file."

## Single source of truth

Put the detect-holder + wait-with-backoff launch wrapper in **one helper**
that every session module imports (e.g. `config/chrome_profile_lock.py`
alongside the stealth-launch helper) — never re-inline a launch-with-retry in
a new module. The wrapper composes with the stealth launch kwargs: it calls
them internally and returns the context, so callers swap one line in their
session `__enter__` and inherit the whole behavior.

A reference implementation lives in the `content-management` project:
`config/chrome_profile_lock.py` exposing
`launch_persistent_context_with_lock_wait(playwright, user_data_dir, *,
headless, logger, backoff_seconds=...)`, with `backoff_seconds` injectable so
the retry/raise/propagate logic is unit-testable without real sleeps.
