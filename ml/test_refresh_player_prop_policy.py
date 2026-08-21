import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ml import refresh_player_prop_policy as refresh_policy


class RefreshPlayerPropPolicyTests(unittest.TestCase):
    def test_through_date_advance_runs_shadow_before_freezing_policy(self):
        def result(command, **_kwargs):
            stdout = '{"policy_id":"daily-policy"}' if command[2:] == [
                "ml.freeze_player_prop_forward_policy",
            ] else ""
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        with (
            patch.object(refresh_policy, "target_games", return_value={}),
            patch.object(refresh_policy, "_lines", return_value=[]),
            patch.object(refresh_policy, "_audit_stale", return_value=False),
            patch.object(refresh_policy, "_read_json", side_effect=[
                {"through": "2026-08-15"},
                {"through": "2026-08-16", "candidate": {"candidate_id": "candidate"}},
            ]),
            patch.object(refresh_policy.subprocess, "run", side_effect=result) as run,
        ):
            report = refresh_policy.refresh("2026-08-16")

        commands = [item.args[0] for item in run.call_args_list]
        self.assertEqual(commands[0][2], "ml.player_prop_reranker_shadow_candidate")
        self.assertIn("--historical-days", commands[0])
        self.assertEqual(commands[1][2], "ml.freeze_player_prop_forward_policy")
        self.assertTrue(report["reranker_shadow_refreshed"])
        self.assertEqual(report["reranker_shadow_candidate_id"], "candidate")

    def test_deferred_game_does_not_advance_settlement_watermark(self):
        with tempfile.TemporaryDirectory() as directory:
            boxes = Path(directory) / "boxes.jsonl"
            boxes.write_text("", encoding="utf-8")

            def result(command, **_kwargs):
                stdout = '{"policy_id":"prior-policy"}' if command[2:] == [
                    "ml.freeze_player_prop_forward_policy",
                ] else ""
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            with (
                patch.object(refresh_policy, "BOXES", boxes),
                patch.object(refresh_policy, "target_games", return_value={7: "2026-08-20"}),
                patch.object(refresh_policy, "_is_final", return_value=False),
                patch.object(refresh_policy, "_audit_stale", return_value=False),
                patch.object(refresh_policy, "_read_json", side_effect=[
                    {"through": "2026-08-18"},
                    {"through": "2026-08-19", "candidate": {"candidate_id": "candidate"}},
                ]),
                patch.object(refresh_policy.subprocess, "run", side_effect=result) as run,
            ):
                report = refresh_policy.refresh("2026-08-20", workers=1)

        shadow_command = run.call_args_list[0].args[0]
        self.assertIn("2026-08-19", shadow_command)
        self.assertEqual(report["requested_through"], "2026-08-20")
        self.assertEqual(report["settled_through"], "2026-08-19")
        self.assertFalse(report["settlement_complete"])
        self.assertEqual(report["deferred_games"], [7])


if __name__ == "__main__":
    unittest.main()
