"""
Example pipeline
================
Minimal template showing the contract every pipeline should follow:

* A ``run(**kwargs)`` function that does the work.
* All progress reported via the project logger (``src.get_logger``).
* No direct prints — the logger streams to terminal, file and the
  Streamlit live panel automatically.

Replace the body with your real ETL / scraping / analysis code.
"""

from __future__ import annotations

import random
import time

from src import get_logger

log = get_logger("example_pipeline")


def run(steps: int = 10, fail_chance: float = 0.1) -> dict:
    """Run a fake multi-step pipeline and return a small summary dict."""
    log.info("Pipeline starting (steps=%d)", steps)
    warnings = 0

    for i in range(1, steps + 1):
        time.sleep(random.uniform(0.1, 0.4))
        if random.random() < fail_chance:
            warnings += 1
            log.warning("Step %d/%d hit a transient issue, retrying", i, steps)
        else:
            log.info("Step %d/%d done", i, steps)

    log.info("Pipeline finished — %d warnings across %d steps", warnings, steps)
    return {"steps": steps, "warnings": warnings}


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    run()
