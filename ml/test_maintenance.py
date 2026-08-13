import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import call, patch

from ml import maintenance


class PlayerPropAuditMaintenanceTests(unittest.TestCase):
    def test_results_day_does_not_roll_before_west_coast_games_finish(self):
        with patch.dict(os.environ, {"NINTH_MAINTENANCE_ROLLOVER_UTC_HOUR": "9"}):
            self.assertEqual(
                maintenance.maintenance_day(datetime(2026, 8, 11, 2, 30, tzinfo=timezone.utc)),
                "2026-08-10",
            )

    def test_results_day_rolls_after_configured_utc_cutoff(self):
        with patch.dict(os.environ, {"NINTH_MAINTENANCE_ROLLOVER_UTC_HOUR": "9"}):
            self.assertEqual(
                maintenance.maintenance_day(datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)),
                "2026-08-11",
            )

    def test_promotes_complete_models_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            candidate.mkdir()
            for name in ("report.json", "moneyline.joblib", "totals_report.json", "totals.joblib"):
                (candidate / name).write_text("{}", encoding="utf8")
            production = {
                "report": root / "report.json", "moneyline": root / "moneyline.joblib",
                "totals_report": root / "totals_report.json", "totals": root / "totals.joblib",
                "props_report": root / "player_props_report.json", "props": root / "player_props.joblib",
            }
            for path in production.values():
                path.write_text("incumbent", encoding="utf8")

            with (
                patch.object(maintenance, "REPORT", production["report"]),
                patch.object(maintenance, "MODEL", production["moneyline"]),
                patch.object(maintenance, "TOTALS_REPORT", production["totals_report"]),
                patch.object(maintenance, "TOTALS_MODEL", production["totals"]),
                patch.object(maintenance, "PLAYER_PROPS_REPORT", production["props_report"]),
                patch.object(maintenance, "PLAYER_PROPS_MODEL", production["props"]),
                patch.object(maintenance, "promotion_checks", return_value={"passed": True}),
                patch.object(maintenance, "totals_promotion_checks", return_value={"passed": True}),
            ):
                result = maintenance.promote_available_candidates(candidate)

            self.assertEqual(result["promoted_models"], ["moneyline", "totals"])
            self.assertFalse(result["promotion_checks"]["player_props"]["candidate_complete"])
            self.assertEqual(production["moneyline"].read_text(encoding="utf8"), "{}")
            self.assertEqual(production["totals"].read_text(encoding="utf8"), "{}")

    def test_refreshes_live_prop_audit_when_an_input_is_newer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "audit.json"
            build_audit = root / "build-audit.json"
            priced_audit = root / "priced-audit.json"
            snapshots = root / "snapshots.jsonl"
            build_snapshots = root / "build-snapshots.jsonl"
            priced_snapshots = root / "priced-snapshots.jsonl"
            boxes = root / "boxes.jsonl"
            audit.write_text("{}", encoding="utf8")
            build_audit.write_text("{}", encoding="utf8")
            priced_audit.write_text("{}", encoding="utf8")
            snapshots.write_text("{}\n", encoding="utf8")
            build_snapshots.write_text("{}\n", encoding="utf8")
            priced_snapshots.write_text("{}\n", encoding="utf8")
            boxes.write_text("{}\n", encoding="utf8")
            audit.touch()
            snapshots.touch()
            boxes.touch()
            audit_mtime = audit.stat().st_mtime
            boxes_mtime = audit_mtime + 2
            os.utime(boxes, (boxes_mtime, boxes_mtime))

            with (
                patch.object(maintenance, "PLAYER_PROP_AUDIT", audit),
                patch.object(maintenance, "PLAYER_PROP_BUILD_AUDIT", build_audit),
                patch.object(maintenance, "PLAYER_PROP_PRICED_BOARD_AUDIT", priced_audit),
                patch.object(maintenance, "PLAYER_PROP_SNAPSHOTS", snapshots),
                patch.object(maintenance, "PLAYER_PROP_BUILD_SNAPSHOTS", build_snapshots),
                patch.object(maintenance, "PLAYER_PROP_PRICED_BOARD_SNAPSHOTS", priced_snapshots),
                patch.object(maintenance, "PLAYER_BOXSCORES", boxes),
                patch.object(maintenance, "run") as run,
            ):
                self.assertTrue(maintenance.refresh_player_prop_audit())

            self.assertEqual(run.call_args_list, [
                call([
                    maintenance.sys.executable, "-m", "ml.evaluate_live_prop_snapshots",
                ]),
                call([
                    maintenance.sys.executable, "-m", "ml.evaluate_player_prop_builds",
                ]),
                call([
                    maintenance.sys.executable, "-m", "ml.evaluate_player_prop_priced_board",
                ]),
            ])

    def test_skips_live_prop_audit_when_output_is_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "audit.json"
            build_audit = root / "build-audit.json"
            priced_audit = root / "priced-audit.json"
            snapshots = root / "snapshots.jsonl"
            build_snapshots = root / "build-snapshots.jsonl"
            priced_snapshots = root / "priced-snapshots.jsonl"
            boxes = root / "boxes.jsonl"
            snapshots.write_text("{}\n", encoding="utf8")
            build_snapshots.write_text("{}\n", encoding="utf8")
            priced_snapshots.write_text("{}\n", encoding="utf8")
            boxes.write_text("{}\n", encoding="utf8")
            audit.write_text("{}", encoding="utf8")
            build_audit.write_text("{}", encoding="utf8")
            priced_audit.write_text("{}", encoding="utf8")

            with (
                patch.object(maintenance, "PLAYER_PROP_AUDIT", audit),
                patch.object(maintenance, "PLAYER_PROP_BUILD_AUDIT", build_audit),
                patch.object(maintenance, "PLAYER_PROP_PRICED_BOARD_AUDIT", priced_audit),
                patch.object(maintenance, "PLAYER_PROP_SNAPSHOTS", snapshots),
                patch.object(maintenance, "PLAYER_PROP_BUILD_SNAPSHOTS", build_snapshots),
                patch.object(maintenance, "PLAYER_PROP_PRICED_BOARD_SNAPSHOTS", priced_snapshots),
                patch.object(maintenance, "PLAYER_BOXSCORES", boxes),
                patch.object(maintenance, "run") as run,
            ):
                self.assertFalse(maintenance.refresh_player_prop_audit())

            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
