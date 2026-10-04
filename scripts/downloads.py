"""Preserve observed download counts across replaced and removed release assets."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def update_ledger(previous: dict, patches: list[dict], started_at: str) -> dict:
    ledger = {"started_at": previous.get("started_at", started_at), "assets": copy.deepcopy(previous.get("assets", {}))}
    entries, seen = ledger["assets"], set()
    for patch in patches:
        for asset in patch["assets"]:
            key = f"{patch['repo']}/{asset['tag']}/{asset['name']}"
            seen.add(key)
            old = entries.get(key)
            count, asset_id = asset["downloads"], asset.get("asset_id")
            carried = old["carried"] if old else 0
            if old and (old["asset_id"] != asset_id or count < old["last_count"]):
                carried += old["last_count"]
            entries[key] = {"repo": patch["repo"], "tag": asset["tag"], "name": asset["name"], "asset_id": asset_id, "last_count": count, "carried": carried, "removed": False}
    for key, entry in entries.items():
        if key not in seen:
            entry["removed"] = True
    return ledger


def plan_downloads(root: Path, data: dict) -> dict[Path, bytes]:
    path = root / "docs/data/download-ledger.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    ledger = update_ledger(previous, data["patches"], data["generated_at"])
    data["ledger_started_at"] = ledger["started_at"]
    for patch in data["patches"]:
        entries = {key: entry for key, entry in ledger["assets"].items() if entry["repo"] == patch["repo"]}
        current = sum(asset["downloads"] for asset in patch["assets"])
        carried = sum(entry["carried"] + (entry["last_count"] if entry["removed"] else 0) for entry in entries.values())
        patch.update(downloads_current=current, downloads_carried=carried, download_ledger=entries, downloads=current + carried)
    data["summary"]["downloads"] = sum(p["downloads"] for p in data["patches"])
    return {path: (json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")}
