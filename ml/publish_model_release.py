"""Publish a verified local model release to private Supabase Storage."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ml.model_release import RELEASES


MAX_FREE_UPLOAD_BYTES = 49 * 1024 * 1024


def _settings():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY", "")
    bucket = os.getenv("NINTH_MODEL_BUCKET", "ninth-models")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and a Supabase server secret key are required")
    return url, key, bucket


def _request(url, key, method="GET", data=None, headers=None):
    request = Request(url, data=data, method=method, headers={
        "apikey": key, "Authorization": f"Bearer {key}", **(headers or {}),
    })
    try:
        with urlopen(request, timeout=180) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[-1000:]
        raise RuntimeError(f"Supabase Storage returned {exc.code}: {detail}") from exc


def _download_json(url, key, bucket, object_path, default=None):
    endpoint = f"{url}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(object_path, safe='/')}"
    try:
        return json.loads(_request(endpoint, key) or b"{}")
    except RuntimeError as exc:
        if "returned 404" in str(exc):
            return default
        raise


def ensure_private_bucket(url, key, bucket):
    endpoint = f"{url}/storage/v1/bucket/{quote(bucket, safe='')}"
    try:
        payload = json.loads(_request(endpoint, key) or b"{}")
        if payload.get("public"):
            raise RuntimeError(f"model bucket {bucket!r} must be private")
        return
    except RuntimeError as exc:
        if "returned 404" not in str(exc):
            raise
    _request(
        f"{url}/storage/v1/bucket", key, method="POST",
        data=json.dumps({
            "id": bucket, "name": bucket, "public": False,
            "fileSizeLimit": MAX_FREE_UPLOAD_BYTES,
            "allowedMimeTypes": [
                "application/gzip",
                "application/json",
                "application/octet-stream",
            ],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _upload_payload(url, key, bucket, object_path, data, filename):
    if len(data) > MAX_FREE_UPLOAD_BYTES:
        raise RuntimeError(f"{filename} exceeds the Supabase Free per-file upload limit")
    endpoint = f"{url}/storage/v1/object/{quote(bucket, safe='')}/{quote(object_path, safe='/')}"
    _request(endpoint, key, method="POST", data=data, headers={
        "Content-Type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
        "x-upsert": "true",
        "Cache-Control": "no-cache",
    })


def _upload(url, key, bucket, object_path, source):
    _upload_payload(url, key, bucket, object_path, source.read_bytes(), source.name)


def _release_objects(manifest):
    release_id = str(manifest["release_id"])
    prefix = f"releases/{release_id}/"
    objects = [f"releases/{entry['stored_path']}" for entry in manifest.get("files", [])]
    objects.append(f"{prefix}manifest.json")
    if any(not path.startswith(prefix) for path in objects):
        raise RuntimeError(f"invalid object path in release manifest: {release_id}")
    return objects


def _retention_history(history, manifest, keep):
    records = [
        row for row in (history or {}).get("releases", [])
        if isinstance(row, dict) and row.get("release_id") != manifest["release_id"]
    ]
    records.append({
        "release_id": manifest["release_id"],
        "created_at": manifest.get("created_at"),
        "objects": _release_objects(manifest),
    })
    keep = max(2, int(keep))
    return records[-keep:], records[:-keep]


def _delete_objects(url, key, bucket, objects):
    endpoint = f"{url}/storage/v1/object/{quote(bucket, safe='')}"
    for offset in range(0, len(objects), 1000):
        batch = objects[offset:offset + 1000]
        if batch:
            _request(
                endpoint, key, method="DELETE",
                data=json.dumps({"prefixes": batch}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )


def publish(release_id: str) -> dict:
    url, key, bucket = _settings()
    release_dir = RELEASES / release_id
    manifest_path = release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_id") != release_id:
        raise RuntimeError(f"invalid release manifest: {release_id}")
    if manifest.get("git_dirty") is True and os.getenv(
        "NINTH_ALLOW_DIRTY_MODEL_RELEASE", "0",
    ).lower() not in {"1", "true", "yes"}:
        raise RuntimeError(
            "refusing to publish a model release built from an uncommitted worktree"
        )
    ensure_private_bucket(url, key, bucket)
    history = _download_json(url, key, bucket, "production/history.json", {"releases": []})
    for entry in manifest.get("files", []):
        source = release_dir.parent / entry["stored_path"]
        _upload(url, key, bucket, f"releases/{entry['stored_path']}", source)
    # Switch production only after every immutable release object exists.
    _upload(url, key, bucket, f"releases/{release_id}/manifest.json", manifest_path)
    _upload(url, key, bucket, "production/manifest.json", manifest_path)
    retained, expired = _retention_history(
        history, manifest, os.getenv("NINTH_MODEL_RELEASE_RETENTION", "14"),
    )
    for record in expired:
        prefix = f"releases/{record.get('release_id')}/"
        objects = [path for path in record.get("objects", []) if str(path).startswith(prefix)]
        _delete_objects(url, key, bucket, objects)
    history_payload = json.dumps({
        "schema_version": 1,
        "updated_at": manifest.get("created_at"),
        "releases": retained,
    }, separators=(",", ":")).encode("utf-8")
    _upload_payload(
        url, key, bucket, "production/history.json", history_payload, "history.json",
    )
    return {
        "status": "published", "release_id": release_id,
        "files": len(manifest.get("files", [])), "bucket": bucket,
        "retained_releases": len(retained), "pruned_releases": len(expired),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_id")
    args = parser.parse_args()
    print(json.dumps(publish(args.release_id)))


if __name__ == "__main__":
    main()
