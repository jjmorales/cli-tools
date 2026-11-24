"""Output file naming and the skip / new-version decision."""
from __future__ import annotations

import json
import re
from pathlib import Path


def existing_versions(out_dir: Path, stem: str):
    """Returns [(version, path)] for <stem>.json (v1), <stem>.v2.json, ..."""
    pat = re.compile(rf"^{re.escape(stem)}(?:\.v(\d+))?\.json$")
    found = []
    if out_dir.is_dir():
        for p in out_dir.iterdir():
            m = pat.match(p.name)
            if m:
                found.append((int(m.group(1)) if m.group(1) else 1, p))
    return sorted(found)


def versioned_path(out_dir: Path, stem: str, version: int) -> Path:
    return out_dir / (f"{stem}.json" if version == 1 else f"{stem}.v{version}.json")


def plan_output(out_dir: Path, src: Path, shash: str, sethash: str, force: bool):
    """Decide what to do for one input. Returns (action, target_path, version).

    action is "skip" (identical output already exists), "overwrite" (--force over
    the matching file) or "create" (first file, or a new version).
    """
    versions = existing_versions(out_dir, src.stem)
    for version, path in versions:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # unreadable file: never matches
        if (
            meta.get("source") == src.name
            and meta.get("source_hash") == shash
            and meta.get("settings_hash") == sethash
        ):
            return ("overwrite" if force else "skip"), path, version
    next_version = (versions[-1][0] + 1) if versions else 1
    return "create", versioned_path(out_dir, src.stem, next_version), next_version
