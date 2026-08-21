"""Vercel adapter for the existing dependency-light MLB HTTP handler."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("NINTH_ARTIFACT_DIR", "/tmp/ninth/artifacts")
os.environ.setdefault("NINTH_DATA_DIR", "/tmp/ninth/data")
os.environ.setdefault("NINTH_MAINTENANCE_CATCHUP_ENABLED", "0")

from ml.artifact_store import ensure_current

ensure_current()
spec = importlib.util.spec_from_file_location("ninth_stats_service", ROOT / "stats-service" / "app.py")
stats_service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats_service)


class handler(stats_service.Handler):
    def _prepare(self):
        ensure_current()
        prefix = "/api/stats"
        if self.path == prefix:
            self.path = "/"
        elif self.path.startswith(prefix + "/"):
            self.path = self.path[len(prefix):]

    def do_GET(self):
        self._prepare()
        return super().do_GET()

    def do_POST(self):
        self._prepare()
        return super().do_POST()
