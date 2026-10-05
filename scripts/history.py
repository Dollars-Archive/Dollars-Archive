"""Normalize documented patch changes and derive current translation coverage."""

from datetime import datetime, timedelta, timezone
import re

CHIPS = ("title", "ui", "dialogue", "image", "video")
ACTIONS = ("added", "partial", "improved", "fixed")
KST = timezone(timedelta(hours=9))


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+(?:\.\d+)*", value):
        return None
    parts = tuple(int(n) for n in value.removeprefix("v").split("."))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def day(value):
    if not isinstance(value, str) or not value:
        return ""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return ""
        return parsed.astimezone(KST).date().isoformat()
    except ValueError:
        return ""


def normalize_history(repo, versions, releases, tags, commit_dates=None, latest_tag=None):
    warnings, entries, seen = [], [], set()
    def warn(kind, message):
        warnings.append({"repo": repo, "type": kind, "message": message})

    release_map = {version_key(r.get("tag_name")): r for r in releases
                   if not r.get("draft") and version_key(r.get("tag_name")) is not None}
    tag_map = {version_key(t.get("name")): t for t in tags
               if version_key(t.get("name")) is not None}
    commit_dates = commit_dates or {}
    if versions is None:
        versions = []
    if not isinstance(versions, list):
        warn("changelog-invalid", "versions는 버전 기록 목록이어야 합니다.")
        versions = []
    for item in versions:
        if not isinstance(item, dict) or version_key(item.get("v")) is None:
            warn("changelog-invalid", "숫자 버전 v가 없는 변경 기록을 제외했습니다.")
            continue
        key = version_key(item["v"])
        if key in seen:
            warn("changelog-invalid", f"{item['v']}: 같은 버전의 중복 기록을 제외했습니다.")
            continue
        seen.add(key)
        version = item["v"].removeprefix("v")
        entry = {"v": version}
        for action in ACTIONS:
            values = item.get(action, [])
            if not isinstance(values, list):
                warn("changelog-invalid", f"{version}: {action}는 문자열 목록이어야 합니다.")
                values = []
            if any(not isinstance(v, str) or not v.strip() for v in values):
                warn("changelog-invalid", f"{version}: {action}의 잘못된 항목을 제외했습니다.")
            entry[action] = list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))
        entry["note"] = item.get("note", "") if isinstance(item.get("note", ""), str) else ""
        release, tag = release_map.get(key), tag_map.get(key)
        explicit = day(item.get("date"))
        if item.get("date") and not explicit:
            warn("changelog-invalid", f"{version}: date 형식이 잘못되어 자동 날짜를 사용합니다.")
        published = day((release or {}).get("published_at"))
        tagged = day(commit_dates.get((tag or {}).get("name", "")))
        entry["date"] = explicit or published or tagged
        entry["date_source"] = "manual" if explicit else "release" if published else "tag" if tagged else ""
        entry["url"] = (release or {}).get("html_url", "")
        if key not in tag_map:
            warn("changelog-orphan", f"{version}: 해당하는 Git 태그가 없습니다.")
        if not any(entry[action] for action in ACTIONS):
            warn("changelog-empty-entry", f"{version}: 변경 내용이 기록되어 있지 않습니다.")
        entries.append(entry)
    entries.sort(key=lambda e: version_key(e["v"]), reverse=True)
    latest_key = version_key(latest_tag)
    if latest_key is not None and latest_key not in seen:
        warn("changelog-missing", f"{latest_tag}: 최신 릴리스의 변경 기록이 없습니다.")
    scope = {chip: {"state": "none", "since": None} for chip in CHIPS}
    oldest = version_key(entries[-1]["v"]) if entries else None
    for entry in reversed(entries):
        for chip in entry["added"]:
            if chip in scope:
                if scope[chip]["state"] != "done":
                    scope[chip]["since"] = None if version_key(entry["v"]) == oldest else entry["v"]
                scope[chip]["state"] = "done"
        for chip in entry["partial"]:
            if chip in scope:
                scope[chip] = {"state": "partial", "since": None}
    return scope, entries, warnings
