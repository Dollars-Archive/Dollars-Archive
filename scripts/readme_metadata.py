"""Read the public, editable Korean-patch README form without guessing coverage."""

import html
import re
from datetime import datetime

HEADINGS = {"title": "타이틀 한글화", "ui": "메뉴·UI", "dialogue": "대사",
            "image": "이미지 번역", "video": "동영상 자막"}
STATES = {"완료": "done", "일부": "partial", "미작업": "none",
          "해당 없음": "none", "확인 필요": "none"}
FIELDS = {"한글 제목": "title", "원제": "original", "시리즈": "series",
          "개발사": "developer", "발매사": "publisher", "장르": "genre", "장르 상세": "genre_full",
          "플레이타임": "playtime", "지원 판본": "edition",
          "패치 기준 업데이트": "base_update"}


def clean(value):
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"<[^>]*>", "", value).replace("`", "").replace("**", "")
    value = html.unescape(value).replace(r"\|", "|").strip()
    return "" if value in {"—", "-", "미입력"} else value


def parse_readme(repo, text):
    meta, scopes, warnings = {}, {}, []

    def warn(message):
        warnings.append({"repo": repo, "type": "readme-form-invalid", "message": message})

    def block(name):
        start = f"<!-- kr-patch:{name}:v1:start -->"
        end = f"<!-- kr-patch:{name}:v1:end -->"
        if start not in text and end not in text:
            return None
        if text.count(start) != 1 or text.count(end) != 1 or text.index(start) >= text.index(end):
            warn(f"{name}: 공통 양식 마커가 누락·중복되거나 순서가 잘못되었습니다.")
            return None
        return text.split(start, 1)[1].split(end, 1)[0]

    info = block("game-info")
    if info is not None:
        rows = {}
        for line in info.splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
            if len(cells) != 2:
                warn("게임 정보 표는 항목·내용의 두 열이어야 합니다. 값 안의 |는 \\|로 씁니다.")
                continue
            key, value = map(clean, cells)
            if key in rows:
                warn(f"{key}: 중복된 항목은 첫 번째 값을 사용합니다.")
                continue
            rows[key] = value
        title = re.search(r"^# (.+?)(?: 한국어 패치| 한글패치)?\s*$", text, re.M)
        if title:
            meta["title"] = clean(title[1])
        for label, field in FIELDS.items():
            if label in rows:
                meta[field] = rows[label]
        if "genre" in meta and "genre_full" not in meta:
            meta["genre_full"] = meta["genre"]
        if "플랫폼" in rows:
            platforms = []
            for value in re.split(r"\s*/\s*|\s*,\s*|\s*;\s*", rows["플랫폼"]):
                value = re.sub(r"\s*\([^)]*\)", "", value).strip()
                value = {"PlayStation 2": "PS2", "PlayStation 3": "PS3", "Nintendo Switch": "Switch",
                         "Windows": "PC", "Steam": "PC", "PC (Steam)": "PC"}.get(value, value)
                if value and value not in platforms:
                    platforms.append(value)
            meta["platforms"] = platforms
        date = rows.get("일본 발매일", rows.get("출시일"))
        if date is not None:
            match = re.search(r"(\d{4})(?:년\s*|-|\.)(\d{1,2})(?:월\s*|-|\.)(\d{1,2})", date)
            if match:
                try:
                    meta["release_jp"] = datetime(*map(int, match.groups())).date().isoformat()
                except ValueError:
                    warn("발매일이 유효한 날짜가 아닙니다. 기존 정보를 유지합니다.")
            elif not date:
                meta["release_jp"] = ""
            else:
                warn("발매일은 YYYY-MM-DD 또는 YYYY년 M월 D일로 입력합니다.")
        for label in ("Title ID", "제품 번호", "제품번호"):
            if rows.get(label):
                meta["product_id"] = rows[label].split()[0]
                break
        else:
            if any(label in rows for label in ("Title ID", "제품 번호", "제품번호")):
                meta["product_id"] = ""
        for label in ("원제", "플랫폼", "개발사", "장르", "플레이타임"):
            if not rows.get(label):
                warn(f"게임 정보의 {label}이 비어 있습니다.")

    scope = block("scope")
    if scope is not None:
        sections = re.split(r"^## (.+?)\s*$", scope, flags=re.M)
        for key, heading in HEADINGS.items():
            found = [sections[i + 1] for i in range(1, len(sections), 2) if sections[i] == heading]
            if len(found) != 1:
                warn(f"{heading}: 제목이 누락되거나 중복되었습니다. 기존 범위를 유지합니다.")
                continue
            values = re.findall(r"^상태:\s*(.+?)\s*$", found[0], re.M)
            if len(values) != 1 or values[0] not in STATES:
                warn(f"{heading}: 상태를 완료·일부·미작업·해당 없음 중 하나로 입력합니다.")
                continue
            scopes[key] = {"state": STATES[values[0]], "status": values[0], "since": None}
            if values[0] == "확인 필요":
                warn(f"{heading}: 기존 자료만으로 완료 여부를 확인할 수 없습니다.")
    return meta, scopes, warnings


def merge_scope(history_scope, readme_scope):
    result = {key: dict(value) for key, value in history_scope.items()}
    for key, value in readme_scope.items():
        previous = result.get(key, {})
        result[key] = dict(value)
        if value["state"] == "done" and previous.get("state") == "done":
            result[key]["since"] = previous.get("since")
    return result
