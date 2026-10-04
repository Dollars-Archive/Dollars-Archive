"""Fetch small front covers without credentials; plan writes until the hub succeeds."""
from __future__ import annotations

import io
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

USER_AGENT = "Dollars-Archive-KR-Patch-Hub (+https://github.com/Dollars-Archive)"


class FrontParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != "img":
            return
        match = re.search(r" - Box - Front \(([^)]+)\) - \d+x\d+$", attrs.get("alt", ""))
        url = attrs.get("src", "")
        host = urlparse(url).hostname or ""
        if match and urlparse(url).scheme == "https" and host in {"images.launchbox-app.com", "gamesdb-images.launchbox.gg"}:
            self.candidates.append({"source_image": url, "image_type": "Box - Front", "region": match[1]})


def parse_front_cover(page: str) -> dict | None:
    parser = FrontParser()
    parser.feed(page)
    return next((c for c in parser.candidates if c["region"] == "Japan"),
                parser.candidates[0] if parser.candidates else None)


class CoverFetcher:
    def __init__(self):
        self.last_request = None

    def __call__(self, url: str) -> bytes:
        if urlparse(url).scheme != "https":
            raise ValueError("표지 URL은 HTTPS여야 합니다.")
        if self.last_request is not None:
            time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=15) as response:
            content = response.read(12 * 1024 * 1024 + 1)
        if len(content) > 12 * 1024 * 1024:
            raise ValueError("표지 응답이 너무 큽니다.")
        return content


def thumbnail(content: bytes) -> bytes:
    with Image.open(io.BytesIO(content)) as original:
        image = ImageOps.exif_transpose(original)
        if image.width > 320:
            image = image.resize((320, max(1, round(image.height * 320 / image.width))), Image.Resampling.LANCZOS)
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        out = io.BytesIO()
        image.save(out, "WEBP", quality=82, method=6)
        return out.getvalue()


def plan_covers(root: Path, data: dict, metadata: dict, refresh=False, fetch=None) -> dict[Path, bytes]:
    fetch = fetch or CoverFetcher()
    provenance_path = root / "docs/data/covers.json"
    previous = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
    provenance, outputs = {}, {}
    for patch in data["patches"]:
        repo = patch["repo"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo) or repo in {".", ".."}:
            raise ValueError("잘못된 표지 저장소 이름")
        meta = metadata.get(repo, {})
        manual, source = meta.get("cover", ""), meta.get("launchbox_url", "")
        patch.update(cover=None, cover_source=source or None)
        relative = f"covers/{repo}.webp"
        destination = root / "docs" / relative
        cached = previous.get(repo, {})
        identity = manual or source
        if destination.exists() and not refresh and cached.get("input") == identity:
            patch["cover"] = relative
            provenance[repo] = cached
            continue
        if not identity:
            data["warnings"].append({"repo": repo, "type": "missing-launchbox", "message": "표지 출처가 없어 표지를 비워 둡니다."})
            continue
        try:
            if manual:
                details = {"source_image": manual, "image_type": "Box - Front", "region": "manual"}
                if manual.startswith("https://"):
                    content = fetch(manual)
                else:
                    path = (root / manual).resolve()
                    allowed = (root / "docs/covers").resolve()
                    if not path.is_relative_to(allowed):
                        raise ValueError("수동 표지는 docs/covers 안에 있어야 합니다.")
                    content = path.read_bytes()
            else:
                parsed = urlparse(source)
                if parsed.scheme != "https" or parsed.hostname != "gamesdb.launchbox-app.com" or not re.fullmatch(r"/games/details/\d+-[a-z0-9-]+/?", parsed.path):
                    raise ValueError("LaunchBox 게임 상세 페이지 주소를 확인하세요.")
                details = parse_front_cover(fetch(source).decode("utf-8"))
                if not details:
                    raise ValueError("Box - Front 표지가 없습니다.")
                content = fetch(details["source_image"])
            outputs[destination] = thumbnail(content)
            provenance[repo] = {"input": identity, "source_page": source or None, **details, "fetched_at": data["generated_at"]}
            patch["cover"] = relative
        except Exception as exc:
            # A cover must not prevent patch metadata and download counts updating.
            data["warnings"].append({"repo": repo, "type": "cover-fetch-failed", "message": f"표지 수집 실패 ({type(exc).__name__}); 표지를 비워 둡니다."})
            if destination.exists() and cached.get("input") == identity:
                patch["cover"] = relative
                provenance[repo] = cached
    data["warnings"].sort(key=lambda w: (w["repo"].lower(), w["type"]))
    outputs[provenance_path] = (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return outputs
