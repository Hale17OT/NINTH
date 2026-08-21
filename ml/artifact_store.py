"""Synchronize the approved NINTH runtime release from private object storage."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.Lock()
_STATE = {"checked_at": 0.0, "release_id": None}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(base_url, key, bucket, object_path, destination):
    endpoint = f"{base_url}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(object_path, safe='/')}"
    request = Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urlopen(request, timeout=180) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def _download_from_proxy(proxy_url, token, object_path, destination):
    separator = "&" if "?" in proxy_url else "?"
    sign_url = f"{proxy_url}{separator}{urlencode({'path': object_path})}"
    request = Request(sign_url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(request, timeout=30) as response:
        signed_url = json.load(response)["url"]
    with urlopen(signed_url, timeout=180) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def ensure_current(force=False):
    """Download, verify and atomically activate the production manifest."""
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY", "")
    bucket = os.getenv("NINTH_MODEL_BUCKET", "ninth-models")
    proxy_base = os.getenv("NINTH_MODEL_API_URL", "").rstrip("/")
    if not proxy_base and os.getenv("VERCEL_URL"):
        proxy_base = f"https://{os.environ['VERCEL_URL'].strip('/')}"
    proxy_url = os.getenv("NINTH_MODEL_PROXY_URL", "") or (
        f"{proxy_base}/api/internal/model-artifacts/sign" if proxy_base else ""
    )
    proxy_token = os.getenv("NINTH_MODEL_PROXY_TOKEN", "")
    direct_storage = bool(base_url and key)
    proxied_storage = bool(proxy_url and proxy_token)
    if not direct_storage and not proxied_storage:
        return {"status": "bundled", "release_id": None}
    download = (
        (lambda object_path, destination: _download(base_url, key, bucket, object_path, destination))
        if direct_storage
        else (lambda object_path, destination: _download_from_proxy(proxy_url, proxy_token, object_path, destination))
    )
    ttl = max(30, int(os.getenv("NINTH_MODEL_SYNC_SECONDS", "300")))
    with _LOCK:
        checked_at = _STATE["checked_at"]
        if not force and checked_at > 0 and time.monotonic() - checked_at < ttl:
            return {"status": "current", "release_id": _STATE["release_id"]}
        stage = Path(tempfile.mkdtemp(prefix="ninth-model-sync-"))
        try:
            manifest_file = stage / "manifest.json"
            download("production/manifest.json", manifest_file)
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            release_id = str(manifest["release_id"])
            artifact_dir = Path(os.getenv("NINTH_ARTIFACT_DIR", "/tmp/ninth/artifacts"))
            data_dir = Path(os.getenv("NINTH_DATA_DIR", "/tmp/ninth/data"))
            marker = artifact_dir / ".release.json"
            try:
                active = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                active = {}
            if active.get("release_id") != release_id:
                for entry in manifest.get("files", []):
                    stored = stage / Path(entry["stored_path"]).name
                    remote = f"releases/{entry['stored_path']}"
                    download(remote, stored)
                    if _sha256(stored) != entry["sha256"]:
                        raise RuntimeError(f"model release checksum mismatch: {entry['logical_path']}")
                    logical = Path(entry["logical_path"])
                    root = artifact_dir if logical.parts[0] == "artifacts" else data_dir
                    target = root / Path(*logical.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + ".incoming")
                    if entry.get("compression") == "gzip":
                        with gzip.open(stored, "rb") as source, temporary.open("wb") as output:
                            shutil.copyfileobj(source, output, length=1024 * 1024)
                    else:
                        shutil.copy2(stored, temporary)
                    os.replace(temporary, target)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                temporary_marker = marker.with_suffix(".incoming")
                temporary_marker.write_text(json.dumps({
                    "release_id": release_id,
                    "release_sha256": manifest.get("release_sha256"),
                    "activated_at": time.time(),
                }), encoding="utf-8")
                os.replace(temporary_marker, marker)
            _STATE.update({"checked_at": time.monotonic(), "release_id": release_id})
            return {"status": "activated", "release_id": release_id}
        finally:
            shutil.rmtree(stage, ignore_errors=True)
