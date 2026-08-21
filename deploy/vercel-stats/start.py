"""Start the production stats service after installing the current model release."""
from __future__ import annotations

import runpy

from ml.artifact_store import ensure_current


ensure_current()
runpy.run_path("stats-service/app.py", run_name="__main__")
