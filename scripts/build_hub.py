#!/usr/bin/env python3
"""Build the profile, patch catalogue and cached front-cover thumbnails."""

from __future__ import annotations

import argparse
import base64
import difflib
import html
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import yaml

if __package__:
    from .covers import plan_covers
    from .downloads import plan_downloads
    from .history import day, normalize_history, version_key, release_additions
    from .readme_metadata import parse_readme, merge_scope
else:
    from covers import plan_covers
    from downloads import plan_downloads
    from history import day, normalize_history, version_key, release_additions
    from readme_metadata import parse_readme, merge_scope

OWNER = "Dollars-Archive"
API = "https://api.github.com"
PROFILE_URL = f"https://github.com/{OWNER}"
HUB_URL = f"https://dollars-archive.github.io/{OWNER}/"
KST = timezone(timedelta(hours=9), "KST")
START = b"<!-- KR-PATCH-HUB:START -->"
END = b"<!-- KR-PATCH-HUB:END -->"
STATUSES = {"auto", "wip", "released", "paused"}
STATUS_LABELS = {"released": "배포", "wip": "작업 중", "paused": "중단"}
RELATED_TITLES = {
    "Game-Localization-Discovery-Archive": "한글화 후보 발굴 아카이브",
    "Dollars-Archive-kr-localization-archive": "제작 기술 노트 아카이브",
}


class BuildError(RuntimeError):
    pass


def iso_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def is_patch_release(release: dict) -> bool:
    return bool(re.match(r"^v\d", release.get("tag_name", "")))


def resolve_status(metadata: dict, patch_releases: list[dict]) -> str:
    status = metadata.get("status", "auto")
    return ("released" if patch_releases else "wip") if status == "auto" else status


def load_metadata(path: Path) -> dict:
    # BaseLoader preserves dates and leading zeroes in Title IDs as strings.
    data = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=yaml.BaseLoader)
    if not isinstance(data, dict):
        raise BuildError("patches.yml의 최상위 값은 저장소 이름을 키로 하는 매핑이어야 합니다.")
    for repo, item in data.items():
        if not isinstance(item, dict):
            raise BuildError(f"{repo}: 메타데이터는 매핑이어야 합니다.")
        for key, value in item.items():
            if key == "versions":
                # History validation is nonfatal and reported per entry later.
                continue
            elif key == "platforms":
                if not isinstance(value, list) or not all(isinstance(p, str) and p for p in value):
                    raise BuildError(f"{repo}: platforms는 문자열 목록이어야 합니다.")
            elif not isinstance(value, str):
                raise BuildError(f"{repo}: {key}는 문자열이어야 합니다.")
        if item.get("status", "auto") not in STATUSES:
            raise BuildError(f"{repo}: status는 auto/wip/released/paused 중 하나여야 합니다.")
        if item.get("release_jp"):
            try:
                datetime.strptime(item["release_jp"], "%Y-%m-%d")
            except ValueError as exc:
                raise BuildError(f"{repo}: release_jp는 YYYY-MM-DD 형식이어야 합니다.") from exc
        if item.get("guide_url") and not public_http_url(item["guide_url"]):
            raise BuildError(f"{repo}: guide_url은 공개 HTTP(S) URL이어야 합니다.")
    return data


def public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.activity_exclusions = json.loads((Path(__file__).with_name("activity-exclusions.json")).read_text(encoding="utf-8"))

    def get(self, url: str, allow_404: bool = False) -> tuple[object, str | None]:
        if url.startswith("/"):
            url = API + url
        if urlparse(url).netloc != "api.github.com" or urlparse(url).scheme != "https":
            raise BuildError("GitHub API 이외의 URL로 인증 요청을 보내지 않습니다.")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Dollars-Archive-patch-hub"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers=headers), timeout=30) as response:
                    result = json.load(response)
                    link = response.headers.get("Link", "")
                match = re.search(r'<([^>]+)>;\s*rel="next"', link)
                return result, match.group(1) if match else None
            except HTTPError as exc:
                if exc.code == 404 and allow_404:
                    return None, None
                if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                # Do not print request headers, token, or response bodies.
                raise BuildError(f"GitHub API 요청 실패: HTTP {exc.code}, {urlparse(url).path}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise BuildError(f"GitHub API 네트워크 오류: {urlparse(url).path}") from exc
            except (ValueError, UnicodeError) as exc:
                raise BuildError(f"GitHub API 응답을 읽을 수 없습니다: {urlparse(url).path}") from exc
        raise BuildError("GitHub API 재시도 실패")

    def paginate(self, path: str) -> list[dict]:
        items, seen = [], set()
        while path:
            if path in seen:
                raise BuildError("GitHub API 페이지네이션이 반복됩니다.")
            seen.add(path)
            page, path = self.get(path)
            if not isinstance(page, list):
                raise BuildError("GitHub API 목록 응답 형식이 잘못되었습니다.")
            items.extend(page)
        return items

    def repositories(self) -> list[dict]:
        repos = self.paginate(f"/users/{OWNER}/repos?per_page=100&type=owner")
        return [r for r in repos if not r.get("fork") and not r.get("archived") and not r.get("private")]

    def releases(self, repo: str) -> list[dict]:
        return [r for r in self.paginate(f"/repos/{OWNER}/{repo}/releases?per_page=100") if not r.get("draft")]

    def readme(self, repo: str) -> str:
        data, _ = self.get(f"/repos/{OWNER}/{repo}/readme", allow_404=True)
        if data is None:
            return ""
        try:
            return base64.b64decode(data["content"]).decode("utf-8-sig")
        except (KeyError, ValueError, UnicodeError) as exc:
            raise BuildError(f"{repo}: README 응답을 해석할 수 없습니다.") from exc

    def tags(self, repo: str) -> list[dict]:
        return self.paginate(f"/repos/{OWNER}/{repo}/tags?per_page=100")

    def walkthroughs(self) -> list[dict]:
        data, _ = self.get(f'/repos/{OWNER}/Game-Walkthrough-Archive/contents/docs/data/guides.json', allow_404=True)
        if data is None:
            return []
        catalogue = json.loads(base64.b64decode(data['content']).decode('utf-8'))
        guides = catalogue.get('guides')
        if not isinstance(guides, list) or any(not isinstance(g, dict) or not isinstance(g.get('patch_repo'), str)
                or not isinstance(g.get('title'), str) or not public_http_url(g.get('url', '')) for g in guides):
            raise BuildError('공략집 목록 형식이 잘못되었습니다.')
        return guides

    def activity_date(self, repo: dict) -> str:
        """Exclude only a recorded maintenance push; subsequent pushes still count."""
        record = self.activity_exclusions.get(repo["name"])
        if not record or repo["pushed_at"] != record["ignored_pushed_at"]:
            return repo["pushed_at"]
        branch = quote(repo.get("default_branch") or "main", safe="")
        commits, _ = self.get(f"/repos/{OWNER}/{repo['name']}/commits?sha={branch}&per_page=1")
        if isinstance(commits, list) and commits and commits[0].get("sha") == record["commit"]:
            return record["previous_activity_at"]
        return repo["pushed_at"]

    def tag_date(self, repo: str, sha: str) -> str:
        data, _ = self.get(f"/repos/{OWNER}/{repo}/commits/{sha}", allow_404=True)
        return ((data or {}).get("commit", {}).get("committer", {}).get("date") or "")


def guide_status(url: str) -> int | None:
    # Never forward the GitHub credential to Pages or other guide hosts.
    try:
        request = Request(url, headers={"User-Agent": "Dollars-Archive-patch-hub"})
        with urlopen(request, timeout=20) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, ValueError):
        return None


def warning(repo: str, kind: str, message: str) -> dict:
    return {"repo": repo, "type": kind, "message": message}


def has_release_link(readme: str) -> bool:
    # GitHub URLs (also autolinked when bare), Markdown relative links, HTML hrefs.
    return any(re.search(pattern, readme, re.IGNORECASE) for pattern in (
        r"https://github\.com/[^\s)\]>\"']+/releases(?:[/#?\s)\]>\"']|$)",
        r"\]\(\s*<?[^\s)]*/releases(?:[/#?\s)>]|$)",
        r"href\s*=\s*[\"'][^\"']*/releases(?:[/#?\"']|$)",
    ))


def patch_warnings(patch: dict, readme: str, has_metadata: bool, now: datetime) -> list[dict]:
    repo, result = patch["repo"], []
    latest = patch["latest_release"]
    if latest and latest["asset_count"] == 0:
        result.append(warning(repo, "release-no-asset", f"{latest['tag']} 릴리스에 첨부파일이 없습니다."))
    if patch["status"] == "wip" and now - iso_time(patch.get("activity_at") or patch["pushed_at"]) > timedelta(days=30):
        result.append(warning(repo, "wip-stale", "작업 중인 패치의 마지막 푸시가 30일을 넘었습니다."))
    if not has_metadata:
        result.append(warning(repo, "missing-metadata", "kr-patch topic은 있지만 patches.yml에 게임 정보가 없습니다."))
    if patch["guide_url"] and patch["guide_status"] != 200:
        result.append(warning(repo, "guide-broken", "설치 가이드가 HTTP 200을 반환하지 않습니다."))
    if patch["status"] == "released" and not has_release_link(readme):
        result.append(warning(repo, "readme-no-release-link", "배포 상태인데 README에 /releases 링크가 없습니다."))
    if not patch["description"].strip():
        result.append(warning(repo, "no-description", "저장소 description이 비어 있습니다."))
    if any(a.get("created_at") and a.get("release_published_at") and iso_time(a["created_at"]) - iso_time(a["release_published_at"]) > timedelta(days=1) for a in patch["assets"]):
        result.append(warning(repo, "asset-reuploaded", "릴리스 공개보다 하루 넘게 늦게 생성된 첨부파일이 있습니다."))
    if sum(not patch.get(key, "").strip() for key in ("developer", "genre", "playtime")) >= 2:
        result.append(warning(repo, "missing-facts", "개발사·장르·플레이타임 중 2개 이상이 비어 있습니다."))
    if latest and not patch.get("changelog"):
        result.append(warning(repo, "missing-scope", "릴리스의 버전별 변경 이력이 비어 있습니다."))
    return result


def build_patch(repo: dict, meta: dict, releases: list[dict], check_guide) -> dict:
    published = [r for r in releases if not r.get("draft")]
    patches = sorted([r for r in published if is_patch_release(r)], key=lambda r: (r.get("published_at") or r.get("created_at") or "", r["tag_name"]), reverse=True)
    stable = [r for r in patches if not r.get("prerelease")]
    latest = stable[0] if stable else None
    tools = sorted([r for r in published if not is_patch_release(r)], key=lambda r: (r.get("published_at") or "", r["tag_name"]), reverse=True)
    assets = []
    for release in patches:
        for asset in sorted(release.get("assets", []), key=lambda a: a["name"]):
            assets.append({"name": asset["name"], "tag": release["tag_name"], "url": asset["browser_download_url"], "downloads": asset.get("download_count", 0), "asset_id": asset.get("id"), "created_at": asset.get("created_at"), "release_published_at": release.get("published_at")})
    guide = meta.get("guide_url", "")
    status = check_guide(guide or f"https://dollars-archive.github.io/{repo['name']}/")
    if not guide and status == 200:
        guide = f"https://dollars-archive.github.io/{repo['name']}/"
    return {
        "repo": repo["name"],
        "title": meta.get("title") or repo.get("description") or repo["name"],
        "original": meta.get("original", ""),
        "series": meta.get("series") or "기타",
        "platforms": meta.get("platforms") or [],
        "genre": meta.get("genre", ""),
        "genre_full": meta.get("genre_full") or meta.get("genre", ""),
        "developer": meta.get("developer", ""),
        "publisher": meta.get("publisher", ""),
        "playtime": meta.get("playtime", ""),
        "edition": meta.get("edition", ""),
        "release_jp": meta.get("release_jp", ""),
        "product_id": meta.get("product_id", ""),
        "base_update": meta.get("base_update", ""),
        "note": meta.get("note", ""),
        "cover_caption": meta.get("cover_caption", ""),
        "status": resolve_status(meta, patches),
        "description": repo.get("description") or "",
        "pushed_at": repo["pushed_at"],
        "stars": repo.get("stargazers_count", 0),
        "url": repo["html_url"],
        "has_pages": bool(repo.get("has_pages")),
        "topics": sorted(repo.get("topics", [])),
        "guide_url": guide,
        "guide_status": status if guide else None,
        "latest_release": ({"tag": latest["tag_name"], "name": latest.get("name") or latest["tag_name"], "url": latest["html_url"], "published_at": latest.get("published_at") or latest.get("created_at"), "asset_count": len(latest.get("assets", []))} if latest else None),
        "downloads": sum(a["downloads"] for a in assets),
        "assets": assets,
        "tools": [{"name": r.get("name") or r["tag_name"], "tag": r["tag_name"], "url": r["html_url"]} for r in tools],
    }


def collect(client, metadata: dict, now: datetime, check_guide=guide_status) -> dict:
    patches, related, warnings = [], [], []
    walkthroughs = client.walkthroughs() if hasattr(client, 'walkthroughs') else []
    repos = sorted(client.repositories(), key=lambda r: r["name"].lower())
    for repo in repos:
        # Defense in depth for fixtures and alternate clients.
        if repo.get("fork") or repo.get("archived") or repo.get("private"):
            continue
        name, topics = repo["name"], repo.get("topics", [])
        if "kr-patch" in topics:
            meta = metadata.get(name, {})
            releases, readme = client.releases(name), client.readme(name)
            if 'https://github.com/Dollars-Archive/Game-Walkthrough-Archive/blob/main/REGISTER-GUIDE.md' not in readme:
                warnings.append({'repo': name, 'type': 'walkthrough-registration-missing', 'message': '공략집 등록 지침 연결이 없습니다. 신규 생성 절차의 안내 자동 연결 워크플로를 설치하세요.'})
            readme_meta, readme_scope, form_warnings = parse_readme(name, readme)
            meta = {**meta, **readme_meta}
            warnings.extend(form_warnings)
            patch = build_patch(repo, meta, releases, check_guide)
            patch['walkthroughs'] = [g for g in walkthroughs if g['patch_repo'] == name]
            activity = client.activity_date(repo) if hasattr(client, "activity_date") else repo["pushed_at"]
            published = (patch["latest_release"] or {}).get("published_at")
            patch["activity_at"] = max((value for value in (activity, published) if value), key=iso_time)
            exclusion = getattr(client, 'activity_exclusions', {}).get(name)
            if exclusion:
                patch['activity_exclusion'] = {key: exclusion[key] for key in ('ignored_pushed_at', 'previous_activity_at')}
            tags = client.tags(name)
            release_keys = {version_key(r.get("tag_name")) for r in releases if not r.get("draft") and day(r.get("published_at"))}
            commit_dates = {}
            records = meta.get("versions", [])
            documented = {version_key(e.get("v")) for e in records if isinstance(e, dict)} if isinstance(records, list) else set()
            for tag in tags:
                key = version_key(tag.get("name"))
                if key is not None and key in documented and key not in release_keys:
                    commit_dates[tag["name"]] = client.tag_date(name, tag["commit"]["sha"])
            patch["scope"], patch["changelog"], history_warnings = normalize_history(
                name, records, releases, tags, commit_dates,
                (patch["latest_release"] or {}).get("tag"))
            warnings.extend(history_warnings)
            patch["scope"] = merge_scope(patch["scope"], readme_scope)
            # A newly published addition supersedes an older README's scope value.
            latest_tag = (patch["latest_release"] or {}).get("tag")
            latest_release = next((r for r in releases if r.get('tag_name') == latest_tag), {})
            for key in release_additions(latest_release):
                historical = next((e for e in reversed(patch['changelog']) if key in e['added']), None)
                patch['scope'][key] = {'state': 'done', 'since': historical['v'] if historical and historical != patch['changelog'][-1] else None}
            if meta.get('confirmed_image_status') == 'done':
                previous = patch['scope']['image']
                patch['scope']['image'] = {'state': 'done', 'status': '완료',
                    'since': previous.get('since') if previous['state'] == 'done' else None}
            if readme_meta or readme_scope:
                patch["metadata_source"] = f"{repo['html_url']}/blob/{repo.get('default_branch') or 'main'}/README.md"
            patches.append(patch)
            warnings.extend(patch_warnings(patch, readme, name in metadata or bool(readme_meta), now))
        elif name.lower().endswith("-kr-patch") or "korean-localization" in name.lower():
            warnings.append(warning(name, "missing-topic", "패치 저장소로 보이지만 kr-patch topic이 없어 목록에서 제외했습니다."))
        if "kr-localization-archive" in topics and "kr-patch" not in topics:
            url = f"https://dollars-archive.github.io/{name}/" if repo.get("has_pages") else repo["html_url"]
            related.append({"repo": name, "title": RELATED_TITLES.get(name, name), "url": url, "desc": repo.get("description") or ""})
            if not repo.get("description"):
                warnings.append(warning(name, "no-description", "관련 저장소 description이 비어 있습니다."))
    # Tie-breaking makes ordering reproducible even when API order changes.
    if any(repo['name'] == 'Game-Walkthrough-Archive' for repo in repos):
        related.append({'repo': 'Game-Walkthrough-Archive', 'title': '직접 제작한 공략집 모음',
            'url': 'https://dollars-archive.github.io/Game-Walkthrough-Archive/', 'desc': 'Dollars Archive가 직접 작성한 게임 공략집'})
    patches.sort(key=lambda p: p["repo"].lower())
    patches.sort(key=lambda p: p["activity_at"], reverse=True)
    warnings.sort(key=lambda w: (w["repo"].lower(), w["type"]))
    return {
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "summary": {"total": len(patches), "released": sum(p["status"] == "released" for p in patches), "wip": sum(p["status"] == "wip" for p in patches), "downloads": sum(p["downloads"] for p in patches)},
        "patches": patches,
        "related": related,
        "warnings": warnings,
    }


def semantic_data(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "generated_at"}


def md(value: object) -> str:
    # Avoid breaking Markdown tables or injecting raw HTML from repository metadata.
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;").replace("\r", " ").replace("\n", " ").replace("[", "&#91;").replace("]", "&#93;").replace("*", "&#42;").replace("`", "&#96;")


def md_link(label: str, url: str) -> str:
    if not public_http_url(url):
        return md(label)
    return f"[{md(label)}](<{url.replace('<', '%3C').replace('>', '%3E')}>)"


ASSET_URL = f"https://raw.githubusercontent.com/{OWNER}/{OWNER}/main/assets/profile/"


def themed_image(name: str, alt: str) -> str:
    return f'<picture><source media="(prefers-color-scheme: dark)" srcset="{ASSET_URL}{name}-dark.svg"><img src="{ASSET_URL}{name}-light.svg" alt="{html.escape(alt, quote=True)}" width="100%"></picture>'


def badge(kind: str, label: str) -> str:
    return f'<img src="{ASSET_URL}badge-{kind}.svg" alt="{html.escape(label, quote=True)}" height="22">'


def summary_svg(summary: dict, dark: bool = False) -> bytes:
    bg, ink, muted, line = ("#171C27", "#E6E9F0", "#98A0B0", "#2A3140") if dark else ("#FFFFFF", "#18202E", "#5E6676", "#DADDE5")
    colors = ["#7C98FF", "#5CCB91", "#F0B45A", "#A8B0BE"] if dark else ["#2648D8", "#1E7F4F", "#9A5B00", "#5B6472"]
    fields = [("total", "한글패치"), ("released", "배포 중"), ("wip", "작업 중"), ("downloads", "다운로드")]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="118" viewBox="0 0 960 118" role="img" aria-label="한글패치 현황"><rect x="1" y="1" width="958" height="116" rx="14" fill="{bg}" stroke="{line}"/>']
    for index, (key, label) in enumerate(fields):
        x = 26 + index * 240
        if index:
            parts.append(f'<path d="M{index * 240} 25v68" stroke="{line}"/>')
        parts.extend([f'<rect x="{x}" y="25" width="4" height="14" rx="2" fill="{colors[index]}"/>', f'<text x="{x + 14}" y="37" fill="{muted}" font-family="sans-serif" font-size="14">{label}</text>', f'<text x="{x}" y="88" fill="{ink}" font-family="Arial,sans-serif" font-size="36" font-weight="700">{summary[key]:,}</text>'])
    parts.append("</svg>\n")
    return "".join(parts).encode("utf-8")


def readme_section(data: dict) -> bytes:
    s = data["summary"]
    summary_label = f"한글패치 {s['total']}개 · 배포 {s['released']} · 작업 중 {s['wip']} · 다운로드 {s['downloads']:,}회"
    lines = ["", themed_image("summary", summary_label), "", "## 한글패치 컬렉션", "", f"{summary_label} · {md_link('검색·기종 필터로 찾아보기 →', HUB_URL)}", "", "| 표지 | 게임 | 기종 | 장르 | 상태 | 버전 | 다운로드 | 바로가기 |", "| :---: | :--- | :---: | :--- | :---: | :---: | ---: | :--- |"]
    for p in data["patches"]:
        latest = p["latest_release"]
        links = [md_link("저장소", p["url"])]
        if latest:
            links.append(md_link("릴리스", p["url"] + "/releases/latest"))
        elif p["status"] == "released":
            links.append(md_link("릴리스", p["url"] + "/releases"))
        if p["guide_url"]:
            links.append(md_link("설치 가이드", p["guide_url"]))
        guides = p.get('walkthroughs', [])
        if guides:
            url = guides[0]['url'] if len(guides) == 1 else 'https://dollars-archive.github.io/Game-Walkthrough-Archive/?game=' + quote(p['repo'])
            links.append(md_link('공략집', url))
        platform_kinds = {"Dreamcast": "dc", "PS2": "ps2", "PS3": "ps3", "PSP": "psp", "Vita": "vita", "PS Vita": "vita", "Switch": "switch", "PC": "pc"}
        platforms = " ".join(badge(platform_kinds[plat], plat) if plat in platform_kinds else md(plat) for plat in p["platforms"]) or "미입력"
        version = md_link(latest["tag"], latest["url"]) if latest else "—"
        cover = ""
        if p.get("cover"):
            image_url = f"https://raw.githubusercontent.com/{OWNER}/{OWNER}/main/docs/{p['cover']}"
            if p.get("cover_revision"):
                image_url += "?v=" + p["cover_revision"]
            image = f'<img src="{html.escape(image_url, quote=True)}" width="48" alt="{html.escape(p["title"], quote=True)} 표지">'
            source = p.get("cover_source")
            cover = f'<a href="{html.escape(source, quote=True)}">{image}</a>' if source and public_http_url(source) else image
            if p.get("cover_caption"):
                cover += f'<br><sub>{html.escape(p["cover_caption"])}</sub>'
        title = f"**{md(p['title'])}**"
        lines.append(f"| {cover} | {title} | {platforms} | {md(p.get('genre') or '—')} | {badge(p['status'], STATUS_LABELS[p['status']])} | {version} | **{p['downloads']:,}** | {' · '.join(links)} |")
    if any(p.get("cover_source") for p in data["patches"]):
        lines.extend(["", "<sub>앞표지 출처: LaunchBox Games Database · 駿河屋 · 이미지를 누르면 출처 페이지가 열립니다.</sub>"])
    if data["related"]:
        lines.extend(["", "### 제작 기록과 아카이브", ""])
        for r in data["related"]:
            lines.append(f"- {md_link(r['title'], r['url'])}" + (f" — {md(r['desc'])}" if r["desc"] else ""))
    date = iso_time(data["generated_at"]).astimezone(KST).strftime("%Y-%m-%d")
    lines.extend(["", f"<sub>자동 갱신: {date} (KST) · 다운로드는 패치 첨부파일 기준</sub>", ""])
    if data.get("ledger_started_at"):
        started = iso_time(data["ledger_started_at"]).astimezone(KST).strftime("%Y-%m-%d")
        lines.extend([f"<sub>누적 집계 시작일: {started} (KST) · 매시간 갱신 · 집계 시작 전 삭제된 다운로드는 포함하지 않습니다.</sub>", ""])
    return "\n".join(lines).encode("utf-8")


def update_readme(original: bytes, data: dict) -> bytes:
    section = readme_section(data)
    if START not in original and END not in original:
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        return original + separator + b"\n" + START + section + END + b"\n"
    if original.count(START) != 1 or original.count(END) != 1:
        raise BuildError("README 자동 갱신 마커가 누락되었거나 중복되었습니다.")
    start, end = original.index(START) + len(START), original.index(END)
    if end < start:
        raise BuildError("README 자동 갱신 마커 순서가 잘못되었습니다.")
    return original[:start] + section + original[end:]


def planned_outputs(root: Path, data: dict) -> dict[Path, bytes]:
    json_path, readme_path = root / "docs/data/patches.json", root / "README.md"
    if json_path.exists():
        old = json.loads(json_path.read_text(encoding="utf-8"))
        if semantic_data(old) == semantic_data(data):
            # Retain the actual generation time, including across midnight in KST.
            data = {**data, "generated_at": old["generated_at"]}
    original = readme_path.read_bytes() if readme_path.exists() else b""
    return {
        json_path: (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        readme_path: update_readme(original, data),
        root / "assets/profile/summary-light.svg": summary_svg(data["summary"]),
        root / "assets/profile/summary-dark.svg": summary_svg(data["summary"], dark=True),
    }


def apply_outputs(outputs: dict[Path, bytes]) -> list[Path]:
    changed = [p for p, content in outputs.items() if not p.exists() or p.read_bytes() != content]
    prepared = []
    try:
        for path in changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".hub-", delete=False) as tmp:
                prepared.append((Path(tmp.name), path))
                tmp.write(outputs[path])
        for temporary, destination in prepared:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in prepared:
            temporary.unlink(missing_ok=True)
    return changed


def main(argv=None, client=None, now=None, check_guide=guide_status) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="허브 저장소 루트")
    parser.add_argument("--refresh-covers", action="store_true", help="저장한 표지를 출처에서 다시 수집")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 요약·경고·README diff 출력")
    modes.add_argument("--check", action="store_true", help="생성 결과가 다르면 exit 1, 파일은 쓰지 않음")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        metadata = load_metadata(root / "patches.yml")
        data = collect(client or GitHubClient(), metadata, now or datetime.now(timezone.utc), check_guide)
        download_outputs = plan_downloads(root, data)
        cover_outputs = plan_covers(root, data, metadata, args.refresh_covers)
        # All API collection and generation must succeed before any output is touched.
        outputs = {**download_outputs, **cover_outputs, **planned_outputs(root, data)}
        changed = [p for p, content in outputs.items() if not p.exists() or p.read_bytes() != content]
        print(json.dumps(data["summary"], ensure_ascii=False))
        for w in data["warnings"]:
            print(f"[{w['type']}] {w['repo']}: {w['message']}")
        if args.dry_run:
            path = root / "README.md"
            old = path.read_bytes().decode("utf-8-sig") if path.exists() else ""
            new = outputs[path].decode("utf-8-sig")
            print("".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile="README.md (현재)", tofile="README.md (생성)")), end="")
        elif args.check:
            print("변경 필요: " + ", ".join(str(p.relative_to(root)) for p in changed) if changed else "생성 결과가 일치합니다.")
            return int(bool(changed))
        else:
            applied = apply_outputs(outputs)
            print("갱신: " + ", ".join(str(p.relative_to(root)) for p in applied) if applied else "데이터 변화 없음; 파일을 갱신하지 않습니다.")
        return 0
    except (BuildError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"허브 생성 실패: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
