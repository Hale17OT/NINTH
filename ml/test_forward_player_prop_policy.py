import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ml import freeze_player_prop_forward_policy as forward


class ForwardPlayerPropPolicyTests(unittest.TestCase):
    def test_same_day_policy_is_reused_without_training_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audits = tuple(root / name for name in ("projection.json", "build.json", "model.json"))
            for index, audit in enumerate(audits):
                audit.write_text(json.dumps({"version": index}), encoding="utf-8")
            output = root / "policy.json"
            history = root / "history.jsonl"
            with (
                patch.object(forward, "AUDITS", audits),
                patch.object(forward, "OUTPUT", output),
                patch.object(forward, "HISTORY", history),
            ):
                first = forward.freeze(policy_date="2026-08-08")
                audits[0].write_text('{"changed_after_freeze":true}', encoding="utf-8")
                second = forward.freeze(policy_date="2026-08-08")

            self.assertEqual(second["policy_id"], first["policy_id"])
            self.assertTrue(second["reused"])
            self.assertEqual(len(history.read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(first["training_through"], "2026-08-07")
            self.assertFalse(first["reranker_promoted"])
            self.assertEqual(first["shadow_candidate"]["target_legs"], 3)
            self.assertEqual(first["shadow_candidate"]["minimum_odds"], 1.3)


if __name__ == "__main__":
    unittest.main()
