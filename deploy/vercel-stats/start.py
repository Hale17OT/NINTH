"""Start the production stats service after installing the current model release."""
from __future__ import annotations

import runpy

from ml.artifact_store import ensure_current


release = ensure_current()
print(
    f"[model-release] startup status={release.get('status')} "
    f"release_id={release.get('release_id')}",
    flush=True,
)
runpy.run_path("stats-service/app.py", run_name="__main__")
