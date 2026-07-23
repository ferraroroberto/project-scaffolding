"""
Project configuration
=====================
Single place to read environment-driven settings.  Pipelines and pages
should import from here rather than reading ``os.environ`` directly so
defaults stay consistent.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
LOG_DIR = DATA_DIR / "logs"

# Namespaced (not bare "APP_NAME") to avoid colliding with tray.bat.template's
# own "APP_NAME" process env var (its tray-bookkeeping value, set per-launch
# and inherited by any child shell/process) — see project-scaffolding#184.
# An adopter cloning this scaffold should rename this key to its own project
# (e.g. "<PROJECT>_APP_NAME"), matching whatever it renames APP_NAME to below.
APP_NAME = os.getenv("SCAFFOLD_APP_NAME", "Project Scaffolding")
DEBUG = os.getenv("DEBUG", "0") == "1"
