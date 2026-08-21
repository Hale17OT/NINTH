"""Start the production stats service; readiness performs the verified model sync."""
from __future__ import annotations

import runpy

runpy.run_path("stats-service/app.py", run_name="__main__")
