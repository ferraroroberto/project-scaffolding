#!/usr/bin/env bash
# Install, check or remove the fleet's self-hosted GitHub Actions runner on the
# Mac Mini. Run it as the runner user, in that user's GUI session (the iOS
# Simulator needs one). Guide, prerequisites and safety settings:
# docs/mac-runner.md.
#
#   scripts/mac_runner_setup.sh install   # download, verify, register, start
#   scripts/mac_runner_setup.sh status    # service state + GitHub's view of it
#   scripts/mac_runner_setup.sh remove    # stop, uninstall, deregister
#
# The registration token is read from RUNNER_TOKEN when set. Otherwise it is
# minted with `gh api`, which needs a gh login with admin on the repo; that
# login is a credential on the runner, so mint the token elsewhere and pass it
# in, or `gh auth logout` once the runner is registered.
#
# Environment overrides:
#   RUNNER_REPO  owner/repo the runner registers on (default ferraroroberto/project-scaffolding)
#   RUNNER_NAME  runner name (default mac-mini)
#   RUNNER_DIR   install folder (default ~/actions-runner)
set -euo pipefail

REPO="${RUNNER_REPO:-ferraroroberto/project-scaffolding}"
NAME="${RUNNER_NAME:-mac-mini}"
DIR="${RUNNER_DIR:-$HOME/actions-runner}"
# self-hosted, macOS and ARM64 are added by the runner itself; labels match
# case-insensitively, so the workflow's [self-hosted, macos, arm64, iphone-sim]
# needs only this one custom label.
LABELS="iphone-sim"

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

token() {
  # $1: registration-token | remove-token
  if [ "$1" = registration-token ] && [ -n "${RUNNER_TOKEN:-}" ]; then
    printf '%s' "$RUNNER_TOKEN"
    return
  fi
  command -v gh >/dev/null || die "gh is not installed; set RUNNER_TOKEN instead (docs/mac-runner.md)"
  gh api -X POST "repos/$REPO/actions/runners/$1" --jq .token
}

preflight() {
  [ "$(uname -s)" = Darwin ] || die "this script runs on macOS"
  [ "$(uname -m)" = arm64 ] || die "expected an Apple-silicon Mac (arm64)"
  xcrun simctl help >/dev/null 2>&1 \
    || die "xcrun simctl is unavailable: install Xcode, then sudo xcode-select -s /Applications/Xcode.app"
  if ! xcrun simctl list devices available | grep -q 'iPhone'; then
    runtime="$(xcrun simctl list runtimes available | awk '/^iOS/ {print $NF}' | tail -n 1)"
    [ -n "$runtime" ] || die "no iOS simulator runtime: xcodebuild -downloadPlatform iOS"
    model="$(xcrun simctl list devicetypes | awk -F'[()]' '/^iPhone/ {id=$2} END {print id}')"
    log "creating an iPhone simulator for this user"
    xcrun simctl create "nightly iPhone" "$model" "$runtime" >/dev/null
  fi
  log "ok: macOS arm64, simctl, an available iPhone simulator"
}

install() {
  preflight
  if [ -f "$DIR/.runner" ]; then
    die "a runner is already configured in $DIR; run 'remove' first to re-register"
  fi
  mkdir -p "$DIR"
  cd "$DIR"

  # The latest release's macOS arm64 tarball and the SHA-256 GitHub prints in
  # the release notes, so a tampered or truncated download never installs.
  release="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
  url="$(printf '%s' "$release" | grep -o 'https://[^"]*actions-runner-osx-arm64-[0-9.]*\.tar\.gz' | head -n 1)"
  [ -n "$url" ] || die "no osx-arm64 asset in the latest actions/runner release"
  want="$(printf '%s' "$release" | grep -o 'BEGIN SHA osx-arm64 -->[0-9a-f]\{64\}' | grep -o '[0-9a-f]\{64\}' | head -n 1)"
  [ -n "$want" ] || die "the release notes carry no osx-arm64 SHA-256 to verify against"
  log "downloading $(basename "$url")"
  curl -fsSL -o runner.tar.gz "$url"
  got="$(shasum -a 256 runner.tar.gz | awk '{print $1}')"
  [ "$got" = "$want" ] || die "SHA-256 mismatch: expected $want, got $got"
  tar xzf runner.tar.gz
  rm runner.tar.gz

  ./config.sh --unattended --url "https://github.com/$REPO" --token "$(token registration-token)" \
    --name "$NAME" --labels "$LABELS" --work _work
  ./svc.sh install
  ./svc.sh start
  status
}

status() {
  [ -x "$DIR/svc.sh" ] || die "no runner installed in $DIR"
  (cd "$DIR" && ./svc.sh status) || true
  if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    gh api "repos/$REPO/actions/runners" \
      --jq ".runners[] | select(.name == \"$NAME\") | \"github: \(.name) \(.status) busy=\(.busy) labels=\([.labels[].name] | join(\",\"))\""
  else
    log "github: not checked (no gh login here); check Settings -> Actions -> Runners shows $NAME as Idle"
  fi
}

remove() {
  [ -x "$DIR/config.sh" ] || die "no runner installed in $DIR"
  cd "$DIR"
  ./svc.sh stop || true
  ./svc.sh uninstall || true
  ./config.sh remove --token "${RUNNER_REMOVE_TOKEN:-$(token remove-token)}"
  log "runner $NAME removed from $REPO; $DIR can now be deleted by hand"
}

case "${1:-}" in
  install) install ;;
  status) status ;;
  remove) remove ;;
  *) die "usage: $0 install|status|remove" ;;
esac
