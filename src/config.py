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

# Namespaced (not bare "APP_NAME"): a generic APP_NAME set by any tray.bat up
# the process chain is inherited by every child shell/process — see
# project-scaffolding#184 (this read side) and #264 (the template now sets
# TRAY_APP_NAME and clears an inherited APP_NAME). An adopter cloning this
# scaffold should rename this key to its own project (e.g. "<PROJECT>_APP_NAME").
APP_NAME = os.getenv("SCAFFOLD_APP_NAME", "Project Scaffolding")
DEBUG = os.getenv("DEBUG", "0") == "1"
