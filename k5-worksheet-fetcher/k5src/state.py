"""Per-target manifest: the set of PDF URLs known from the last scan.

This is what makes re-runs incremental — `plan` diffs a fresh crawl against
this file instead of assuming everything needs re-downloading.
"""
import json
import os


def _manifest_path(manifest_dir, target_name):
    return os.path.join(manifest_dir, f"{target_name}.json")


def load_manifest(manifest_dir, target_name):
    path = _manifest_path(manifest_dir, target_name)
    if not os.path.exists(path):
        return {"urls": [], "last_scan": None}
    with open(path) as f:
        return json.load(f)


def save_manifest(manifest_dir, target_name, urls, timestamp):
    os.makedirs(manifest_dir, exist_ok=True)
    path = _manifest_path(manifest_dir, target_name)
    with open(path, "w") as f:
        json.dump({"urls": sorted(urls), "last_scan": timestamp}, f, indent=2)
