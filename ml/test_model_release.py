import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib

from ml import artifact_store, model_release, publish_model_release


class ModelReleaseTests(unittest.TestCase):
    def test_bucket_creation_uses_storage_api_request_fields(self):
        calls = []

        def request(url, _key, method="GET", data=None, headers=None):
            calls.append((url, method, data, headers))
            if method == "GET":
                raise RuntimeError("Supabase Storage returned 404: not found")
            return b'{}'

        with patch.object(publish_model_release, "_request", side_effect=request):
            publish_model_release.ensure_private_bucket(
                "https://example.supabase.co", "test-key", "ninth-models",
            )

        payload = json.loads(calls[-1][2])
        self.assertEqual(payload["fileSizeLimit"], 49 * 1024 * 1024)
        self.assertNotIn("file_size_limit", payload)
        self.assertFalse(payload["public"])

    def test_dirty_release_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            releases = Path(directory)
            release = releases / "dirty-release"
            release.mkdir()
            (release / "manifest.json").write_text(json.dumps({
                "release_id": "dirty-release", "git_dirty": True, "files": [],
            }), encoding="utf-8")
            with (
                patch.object(publish_model_release, "RELEASES", releases),
                patch.dict("os.environ", {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_SECRET_KEY": "test-key",
                    "NINTH_ALLOW_DIRTY_MODEL_RELEASE": "0",
                }, clear=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "uncommitted worktree"):
                    publish_model_release.publish("dirty-release")

    def test_cloud_release_history_prunes_only_expired_release_objects(self):
        history = {"releases": [
            {"release_id": "release-1", "objects": ["releases/release-1/model.joblib"]},
            {"release_id": "release-2", "objects": ["releases/release-2/model.joblib"]},
        ]}
        manifest = {
            "release_id": "release-3", "created_at": "2026-08-21T00:00:00Z",
            "files": [{"stored_path": "release-3/artifacts/model.joblib"}],
        }
        retained, expired = publish_model_release._retention_history(history, manifest, 2)
        self.assertEqual([row["release_id"] for row in retained], ["release-2", "release-3"])
        self.assertEqual([row["release_id"] for row in expired], ["release-1"])
        self.assertEqual(retained[-1]["objects"], [
            "releases/release-3/artifacts/model.joblib",
            "releases/release-3/manifest.json",
        ])

    def test_release_compacts_runtime_logs_and_restores_verified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, data, releases = root / "artifacts", root / "data", root / "releases"
            artifacts.mkdir(); data.mkdir()
            joblib.dump({"report": {"model": "moneyline"}}, artifacts / "moneyline.joblib")
            joblib.dump({"report": {"model": "totals"}}, artifacts / "totals.joblib")
            joblib.dump({"models": {"batter:hits": {}}, "state": {"season": 2026}}, artifacts / "player_props.joblib")
            (artifacts / "report.json").write_text('{"model":"moneyline","trained_through_date":"2026-08-20"}', encoding="utf-8")
            (artifacts / "totals_report.json").write_text('{"model":"totals","trained_through_date":"2026-08-20"}', encoding="utf-8")
            (artifacts / "player_props_report.json").write_text('{"version":3,"data":{"last_date":"2026-08-20"}}', encoding="utf-8")
            rows = [
                {"game_id": 1, "recorded_at": "2026-08-20T10:00:00Z", "scheduled_start": "2026-08-20T12:00:00Z", "value": "first"},
                {"game_id": 1, "recorded_at": "2026-08-20T11:00:00Z", "scheduled_start": "2026-08-20T12:00:00Z", "value": "locked"},
                {"game_id": 1, "recorded_at": "2026-08-20T13:00:00Z", "scheduled_start": "2026-08-20T12:00:00Z", "value": "late"},
            ]
            (data / "projection_snapshots.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
            )
            with (
                patch.object(model_release, "ARTIFACTS", artifacts),
                patch.object(model_release, "DATA", data),
                patch.object(model_release, "RELEASES", releases),
            ):
                manifest = model_release.build_release("release-test")
                projection = next(
                    row for row in manifest["files"]
                    if row["logical_path"] == "data/projection_snapshots.jsonl"
                )
                stored = releases / projection["stored_path"]
                with gzip.open(stored, "rt", encoding="utf-8") as handle:
                    compact = [json.loads(line) for line in handle]
                self.assertEqual([row["value"] for row in compact], ["locked"])
                (artifacts / "report.json").write_text('{"model":"changed"}', encoding="utf-8")
                model_release.restore_release("release-test")
                restored = json.loads((artifacts / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(restored["model"], "moneyline")

    def test_runtime_store_verifies_and_activates_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = gzip.compress(b'{"model":"verified"}')
            entry = {
                "logical_path": "artifacts/report.json",
                "stored_path": "release-1/artifacts/report.json.gz",
                "compression": "gzip",
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            manifest = json.dumps({"release_id": "release-1", "files": [entry]}).encode()
            remote = {
                "production/manifest.json": manifest,
                "releases/release-1/artifacts/report.json.gz": payload,
            }

            def download(_url, _key, _bucket, object_path, destination):
                destination.write_bytes(remote[object_path])

            with (
                patch.object(artifact_store, "_download", side_effect=download),
                patch.dict("os.environ", {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_SERVICE_ROLE_KEY": "test-key",
                    "NINTH_ARTIFACT_DIR": str(root / "artifacts"),
                    "NINTH_DATA_DIR": str(root / "data"),
                }, clear=False),
            ):
                artifact_store._STATE.update({"checked_at": 0.0, "release_id": None})
                result = artifact_store.ensure_current(force=True)
            self.assertEqual(result["release_id"], "release-1")
            restored = json.loads((root / "artifacts" / "report.json").read_text())
            self.assertEqual(restored["model"], "verified")

    def test_runtime_store_can_activate_through_internal_signing_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b'{"model":"proxied"}'
            entry = {
                "logical_path": "artifacts/report.json",
                "stored_path": "release-proxy/artifacts/report.json",
                "compression": None,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            remote = {
                "production/manifest.json": json.dumps({
                    "release_id": "release-proxy", "files": [entry],
                }).encode(),
                "releases/release-proxy/artifacts/report.json": payload,
            }

            def download(proxy_url, token, object_path, destination):
                self.assertEqual(proxy_url, "https://internal.example/api/internal/model-artifacts/sign")
                self.assertEqual(token, "proxy-token")
                destination.write_bytes(remote[object_path])

            with (
                patch.object(artifact_store, "_download_from_proxy", side_effect=download),
                patch.dict("os.environ", {
                    "SUPABASE_URL": "",
                    "SUPABASE_SERVICE_ROLE_KEY": "",
                    "SUPABASE_SECRET_KEY": "",
                    "NINTH_MODEL_API_URL": "https://internal.example",
                    "NINTH_MODEL_PROXY_TOKEN": "proxy-token",
                    "NINTH_ARTIFACT_DIR": str(root / "artifacts"),
                    "NINTH_DATA_DIR": str(root / "data"),
                }, clear=False),
            ):
                artifact_store._STATE.update({"checked_at": 0.0, "release_id": None})
                result = artifact_store.ensure_current(force=True)
            self.assertEqual(result["release_id"], "release-proxy")
            restored = json.loads((root / "artifacts" / "report.json").read_text())
            self.assertEqual(restored["model"], "proxied")

    def test_runtime_store_uses_vercel_deployment_url_when_binding_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = json.dumps({"release_id": "release-empty", "files": []}).encode()

            def download(proxy_url, token, object_path, destination):
                self.assertEqual(proxy_url, "https://ninth-deploy.vercel.app/api/internal/model-artifacts/sign")
                self.assertEqual(token, "proxy-token")
                self.assertEqual(object_path, "production/manifest.json")
                destination.write_bytes(manifest)

            with (
                patch.object(artifact_store, "_download_from_proxy", side_effect=download),
                patch.dict("os.environ", {
                    "SUPABASE_URL": "",
                    "SUPABASE_SERVICE_ROLE_KEY": "",
                    "SUPABASE_SECRET_KEY": "",
                    "NINTH_MODEL_API_URL": "",
                    "NINTH_MODEL_PROXY_URL": "",
                    "NINTH_MODEL_PROXY_TOKEN": "proxy-token",
                    "VERCEL_URL": "ninth-deploy.vercel.app",
                    "NINTH_ARTIFACT_DIR": str(root / "artifacts"),
                    "NINTH_DATA_DIR": str(root / "data"),
                }, clear=False),
            ):
                artifact_store._STATE.update({"checked_at": 0.0, "release_id": None})
                result = artifact_store.ensure_current(force=True)
            self.assertEqual(result["release_id"], "release-empty")


if __name__ == "__main__":
    unittest.main()
