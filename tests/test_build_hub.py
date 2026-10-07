import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import build_hub as hub

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def repo(name="sample-kr-patch", **values):
    return {"name": name, "topics": ["kr-patch"], "description": "샘플 패치", "pushed_at": "2026-10-01T00:00:00Z", "html_url": f"https://github.com/Dollars-Archive/{name}", "has_pages": False, **values}


def release(tag="v1.0", downloads=7, **values):
    return {"tag_name": tag, "name": tag, "published_at": "2026-10-01T00:00:00Z", "html_url": f"https://github.com/Dollars-Archive/sample-kr-patch/releases/tag/{tag}", "draft": False, "prerelease": False, "assets": [{"name": "PC.zip", "browser_download_url": "https://github.com/Dollars-Archive/sample-kr-patch/releases/download/v1.0/PC.zip", "download_count": downloads}], **values}


class FixtureClient:
    def __init__(self, repositories=None, releases=None, readme=None):
        self.repos = repositories if repositories is not None else [repo()]
        self.release_data = releases if releases is not None else [release()]
        self.readme_text = readme if readme is not None else "[다운로드](https://github.com/Dollars-Archive/sample-kr-patch/releases)"

    def repositories(self):
        return copy.deepcopy(self.repos)

    def releases(self, name):
        return copy.deepcopy(self.release_data)

    def readme(self, name):
        return self.readme_text

    def tags(self, name):
        return [{"name": r["tag_name"], "commit": {"sha": "fixture"}} for r in self.release_data if not r.get("draft")]

    def tag_date(self, name, sha):
        return "2026-09-30T16:00:00Z"


class HubTests(unittest.TestCase):
    def catalogue(self, client=None, metadata=None, guide=lambda u: 404):
        return hub.collect(client or FixtureClient(), {"sample-kr-patch": {"title": "게임", "platforms": ["PC"]}} if metadata is None else metadata, NOW, guide)

    def types(self, data):
        return {w["type"] for w in data["warnings"]}

    def test_patch_and_tool_tags(self):
        for tag in ["v1.4.0", "v1.0", "v2.0-beta"]:
            self.assertTrue(hub.is_patch_release(release(tag)))
        for tag in ["trainer-v1.0", "save-manager-v1.0", "1.0", "vNext"]:
            self.assertFalse(hub.is_patch_release(release(tag)))

    def test_tools_and_drafts_excluded_from_downloads(self):
        data = self.catalogue(FixtureClient(releases=[release(downloads=9), release("trainer-v1.0", 999), release("save-manager-v1.0", 999), release("v2.0", 99, draft=True)]))
        self.assertEqual(data["summary"]["downloads"], 9)
        self.assertEqual(len(data["patches"][0]["tools"]), 2)

    def test_latest_is_stable_by_publication_time(self):
        data = self.catalogue(FixtureClient(releases=[release("v10.0", published_at="2026-09-01T00:00:00Z"), release("v1.0", published_at="2026-10-01T00:00:00Z"), release("v11.0", prerelease=True, published_at="2026-10-03T00:00:00Z")]))
        self.assertEqual(data["patches"][0]["latest_release"]["tag"], "v1.0")
        self.assertEqual(data["summary"]["downloads"], 21)

    def test_multi_asset_downloads_retained(self):
        r = release(downloads=9)
        r["assets"].append({**r["assets"][0], "name": "Switch.zip", "download_count": 21})
        p = self.catalogue(FixtureClient(releases=[r]))["patches"][0]
        self.assertEqual(p["downloads"], 30)
        self.assertEqual([a["downloads"] for a in p["assets"]], [9, 21])

    def test_no_asset_warning(self):
        self.assertIn("release-no-asset", self.types(self.catalogue(FixtureClient(releases=[release(assets=[])]))))

    def test_empty_old_release_does_not_warn_for_latest(self):
        self.assertNotIn("release-no-asset", self.types(self.catalogue(FixtureClient(releases=[release(assets=[], published_at="2026-09-01T00:00:00Z"), release("v1.1")]))))

    def test_missing_metadata_succeeds_and_uses_description(self):
        data = self.catalogue(metadata={})
        self.assertEqual(len(data["patches"]), 1)
        self.assertEqual(data["patches"][0]["title"], "샘플 패치")
        self.assertIn("missing-metadata", self.types(data))

    def test_missing_topic_warns_without_listing(self):
        data = self.catalogue(FixtureClient(repositories=[repo(topics=[])]))
        self.assertEqual(data["patches"], [])
        self.assertEqual(self.types(data), {"missing-topic"})

    def test_unrelated_repositories_not_included(self):
        data = self.catalogue(FixtureClient(repositories=[repo("misc", topics=[]), repo("fork-kr-patch", fork=True), repo("old-kr-patch", archived=True), repo("secret-kr-patch", private=True)]))
        self.assertEqual(data["summary"]["total"], 0)
        self.assertEqual(data["warnings"], [])

    def test_related_archive_and_empty_description(self):
        data = self.catalogue(FixtureClient(repositories=[repo("archive", topics=["kr-localization-archive"], description=None, has_pages=True)]))
        self.assertEqual(len(data["related"]), 1)
        self.assertEqual(data["related"][0]["url"], "https://dollars-archive.github.io/archive/")
        self.assertIn("no-description", self.types(data))

    def test_auto_and_explicit_status(self):
        self.assertEqual(hub.resolve_status({}, []), "wip")
        self.assertEqual(hub.resolve_status({}, [release()]), "released")
        self.assertEqual(hub.resolve_status({"status": "paused"}, [release()]), "paused")
        self.assertEqual(hub.resolve_status({"status": "wip"}, [release()]), "wip")

    def test_stale_boundary_over_30_days(self):
        old = repo(pushed_at=(NOW - timedelta(days=30)).isoformat())
        self.assertNotIn("wip-stale", self.types(self.catalogue(FixtureClient([old], releases=[]))))
        old["pushed_at"] = (NOW - timedelta(days=30, seconds=1)).isoformat()
        self.assertIn("wip-stale", self.types(self.catalogue(FixtureClient([old], releases=[]))))

    def test_broken_and_discovered_guides(self):
        meta = {"sample-kr-patch": {"guide_url": "https://example.com/guide"}}
        self.assertIn("guide-broken", self.types(self.catalogue(metadata=meta, guide=lambda u: 404)))
        self.assertIn("guide-broken", self.types(self.catalogue(metadata=meta, guide=lambda u: None)))
        data = self.catalogue(guide=lambda u: 200)
        self.assertEqual(data["patches"][0]["guide_url"], "https://dollars-archive.github.io/sample-kr-patch/")
        self.assertNotIn("guide-broken", self.types(data))
        self.assertEqual(self.catalogue()["patches"][0]["guide_url"], "")

    def test_readme_release_link_and_description_warnings(self):
        data = self.catalogue(FixtureClient(repositories=[repo(description=None)], readme="없음"))
        self.assertTrue({"no-description", "readme-no-release-link"} <= self.types(data))
        self.assertNotIn("readme-no-release-link", self.types(self.catalogue()))

    def test_plain_release_mention_is_not_a_link(self):
        self.assertFalse(hub.has_release_link("다운로드 경로는 /releases 입니다."))
        self.assertTrue(hub.has_release_link("[릴리스](/owner/repo/releases)"))
        self.assertTrue(hub.has_release_link('<a href="/owner/repo/releases">릴리스</a>'))

    def test_sorting_reproducible(self):
        a, b = repo("b-kr-patch"), repo("a-kr-patch")
        first = self.catalogue(FixtureClient([a, b]), metadata={})
        second = self.catalogue(FixtureClient([b, a]), metadata={})
        self.assertEqual(first, second)
        self.assertEqual([p["repo"] for p in first["patches"]], ["a-kr-patch", "b-kr-patch"])

    def test_readme_outside_markers_preserved_byte_for_byte(self):
        prefix = b"\xef\xbb\xbf# Human text\r\n\r\n" + hub.START
        suffix = hub.END + b"\r\n\r\nDo not change.\r\n"
        result = hub.update_readme(prefix + b"\r\nOld\r\n" + suffix, self.catalogue())
        self.assertEqual(result[:len(prefix)], prefix)
        self.assertEqual(result[-len(suffix):], suffix)

    def test_profile_excludes_history_and_escapes_genre_and_caption(self):
        data = self.catalogue(metadata={'sample-kr-patch': {'title': '게임', 'summary': '1.0 : 요약', 'genre': '<script> | RPG', 'genre_full': '전체 장르 설명', 'cover_caption': 'PS4판 표지'}})
        p = data['patches'][0]
        p.update(cover='covers/sample.webp', cover_revision='0123456789ab', cover_source='https://example.com/source')
        section = hub.readme_section(data).decode()
        self.assertIn('&lt;script&gt; &#124; RPG', section)
        self.assertNotIn('1.0 : 요약', section)
        self.assertEqual(p['genre_full'], '전체 장르 설명')
        self.assertIn('PS4판 표지', section)
        self.assertIn('sample.webp?v=0123456789ab', section)

    def test_marker_append_preserves_original_and_invalid_markers_fail(self):
        old = b"user-authored text without newline"
        self.assertTrue(hub.update_readme(old, self.catalogue()).startswith(old))
        for invalid in [hub.START, hub.END, hub.END + hub.START, hub.START + hub.START + hub.END]:
            with self.assertRaises(hub.BuildError):
                hub.update_readme(invalid, self.catalogue())

    def test_no_warnings_hides_readme_details_and_kst_date(self):
        data = self.catalogue()
        data["generated_at"] = "2026-10-04T16:00:00Z"
        section = hub.readme_section(data).decode()
        self.assertNotIn("<details>", section)
        self.assertIn("2026-10-05 (KST)", section)

    def test_metadata_preserves_zeroes_and_validates_types(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "patches.yml"
            path.write_text("game:\n  product_id: 01008BA00F172000\n  release_jp: 2020-02-27\n  platforms: [Switch]\n", encoding="utf-8")
            data = hub.load_metadata(path)
            self.assertEqual(data["game"]["product_id"], "01008BA00F172000")
            self.assertIsInstance(data["game"]["release_jp"], str)
            for invalid in ["game:\n  status: wrong\n", "game:\n  platforms: Switch\n", "game:\n  release_jp: 2020-99-99\n", "game:\n  guide_url: javascript:alert(1)\n"]:
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaises(hub.BuildError):
                    hub.load_metadata(path)

    def test_pagination_collects_every_page(self):
        client = hub.GitHubClient()
        with patch.object(client, "get", side_effect=[([{"page": 1}], "https://api.github.com/next"), ([{"page": 2}], None)]):
            self.assertEqual(client.paginate("/first"), [{"page": 1}, {"page": 2}])

    def test_history_integration_facts_and_missing_history_warnings(self):
        data = self.catalogue(metadata={'sample-kr-patch': {'versions': [{'v': '1.0', 'added': ['ui']}], 'genre': 'RPG'}})
        self.assertEqual(data['patches'][0]['scope']['ui']['state'], 'done')
        self.assertIn('missing-facts', self.types(data))
        self.assertNotIn('changelog-missing', self.types(data))
        self.assertIn('missing-scope', self.types(self.catalogue()))
        self.assertNotIn('missing-facts', self.types(self.catalogue(metadata={'sample-kr-patch': {'developer': '제작사', 'genre': 'RPG'}})))

    def test_bad_versions_do_not_block_metadata_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'patches.yml'
            path.write_text('sample-kr-patch:\n  versions: wrong\n', encoding='utf-8')
            data = self.catalogue(metadata=hub.load_metadata(path))
            self.assertIn('changelog-invalid', self.types(data))

    def test_deleted_release_gets_tag_commit_date(self):
        client = FixtureClient()
        client.tags = lambda name: [{'name': 'v0.9', 'commit': {'sha': 'old'}}, {'name': 'v1.0', 'commit': {'sha': 'current'}}]
        data = self.catalogue(client, {'sample-kr-patch': {'versions': [{'v': '1.0', 'added': ['ui']}, {'v': '0.9', 'fixed': ['버그 수정']}]}})
        self.assertEqual(data['patches'][0]['changelog'][1]['date'], '2026-10-01')
        self.assertEqual(data['patches'][0]['changelog'][1]['date_source'], 'tag')

    def test_credentials_never_sent_to_external_host(self):
        with self.assertRaises(hub.BuildError):
            hub.GitHubClient(token="fake-test-token").get("https://example.com/anything")

    def test_unchanged_data_does_not_change_timestamp_or_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = self.catalogue()
            hub.apply_outputs(hub.planned_outputs(root, data))
            original = {p: p.read_bytes() for p in hub.planned_outputs(root, data)}
            data["generated_at"] = "2026-10-06T16:00:00Z"
            outputs = hub.planned_outputs(root, data)
            self.assertEqual(outputs, original)
            self.assertEqual(hub.apply_outputs(outputs), [])

    def test_cli_dry_run_check_and_api_failure_do_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "patches.yml").write_text("sample-kr-patch:\n  title: 게임\n", encoding="utf-8")
            args = ["--root", str(root)]
            client = FixtureClient()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(hub.main(args + ["--dry-run"], client, NOW, lambda u: 404), 0)
                self.assertFalse((root / "README.md").exists())
                self.assertEqual(hub.main(args + ["--check"], client, NOW, lambda u: 404), 1)
                self.assertEqual(hub.main(args, client, NOW, lambda u: 404), 0)
                original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                self.assertEqual(hub.main(args + ["--check"], client, NOW + timedelta(days=1), lambda u: 404), 0)
                with patch.object(client, "readme", side_effect=hub.BuildError("API failure")):
                    self.assertEqual(hub.main(args, client, NOW, lambda u: 404), 2)
                self.assertEqual({p: p.read_bytes() for p in root.rglob("*") if p.is_file()}, original)


    def test_discovery_match_product_title_manual_and_ambiguity(self):
        text = """# Guardian Angel (가디언 엔젤)

## 한눈에 보기

| 항목 | 내용 |
|---|---|
| 원제 | ガーディアンエンジェル / Guardian Angel |
| 한글 제목 | 가디언 엔젤 |
| 플랫폼 | PlayStation 2 |
| 제품번호 | SLPS-25214 |
"""
        game = hub.parse_discovery_document("platforms/ps2/games/guardian-angel.md", text, "doc-sha")
        index = {"games": [game]}
        patch_data = {"product_id": "slps25214", "original": "wrong", "platforms": ["PS2"], "title": "x", "description": ""}
        self.assertEqual(hub.match_discovery(patch_data, {}, index), (game["key"], "product_id"))

        patch_data["product_id"] = ""
        patch_data["original"] = "ガーディアンエンジェル / Guardian Angel"
        self.assertEqual(hub.match_discovery(patch_data, {}, index), (game["key"], "title"))

        self.assertEqual(hub.match_discovery(patch_data, {"discovery": game["key"]}, index), (game["key"], "manual"))
        self.assertEqual(hub.match_discovery(patch_data, {"discovery": "platforms/ps2/games/missing.md"}, index), ("", "none"))

        duplicate = {**game, "key": "platforms/ps2/games/guardian-angel-copy.md"}
        patch_data["product_id"] = "SLPS-25214"
        self.assertEqual(hub.match_discovery(patch_data, {}, {"games": [game, duplicate]}), ("", "none"))

        patch_data["product_id"] = ""
        patch_data["platforms"] = ["PS3"]
        self.assertEqual(hub.match_discovery(patch_data, {}, index), ("", "none"))

    def test_discovery_collect_warnings_and_fields(self):
        key = "platforms/ps2/games/guardian-angel.md"
        index = {"games": [{
            "key": key, "source_sha": "x", "platform": "PS2",
            "product_id": "SLPS-25214", "original": "Guardian Angel",
            "english_title": "Guardian Angel", "title_ko": "가디언 엔젤", "title": "Guardian Angel"
        }]}
        client = FixtureClient(repositories=[repo("Guardian-Angel-Korean-Localization")], releases=[])
        metadata = {"Guardian-Angel-Korean-Localization": {
            "title": "가디언 엔젤", "original": "Guardian Angel",
            "platforms": ["PS2"], "product_id": "SLPS-25214"
        }}
        data = hub.collect(client, metadata, NOW, lambda u: 404, index)
        self.assertEqual(data["patches"][0]["discovery"], key)
        self.assertEqual(data["patches"][0]["discovery_match"], "product_id")
        self.assertNotIn("discovery-unmatched", self.types(data))

        missing = hub.collect(FixtureClient(repositories=[repo("unknown-kr-patch")], releases=[]),
                              {"unknown-kr-patch": {"platforms": ["PS2"], "title": "Unknown"}},
                              NOW, lambda u: 404, index)
        self.assertEqual(missing["patches"][0]["discovery_match"], "none")
        self.assertIn("discovery-unmatched", self.types(missing))



if __name__ == "__main__":
    unittest.main()
