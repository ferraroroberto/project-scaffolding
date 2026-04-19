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

APP_NAME = os.getenv("APP_NAME", "Project Scaffolding")
DEBUG = os.getenv("DEBUG", "0") == "1"
