import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts import build_hub as hub

ROOT = Path(__file__).resolve().parents[1]

class LibraryClient:
    def __init__(self, records, private):
        self.records, self.private = records, private
    def repositories(self):
        return [{"name": r["repo"], "private": self.private, "topics": ["kr-patch"]} for r in self.records]
    def releases(self, name):
        raise AssertionError("Stopped repository must not be queried")
    def readme(self, name):
        raise AssertionError("Stopped repository must not be queried")

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.records = json.loads((ROOT / "docs/data/library-records.json").read_text(encoding="utf-8"))["records"]
        self.meta = {r["repo"]: {"distribution": "stopped"} for r in self.records}
    def test_public_private_and_missing_repositories_retain_same_seven_records(self):
        original = copy.deepcopy(self.records)
        for private, records in [(False, self.records), (True, self.records), (True, [])]:
            data = hub.collect(LibraryClient(records, private), self.meta, datetime.now(timezone.utc), library_records=self.records)
            self.assertEqual(len(data["patches"]), 7)
            self.assertEqual(data["summary"]["released"], 0)
            self.assertEqual(data["library_count"], 7)
            for p in data["patches"]:
                old = next(r for r in self.records if r["repo"] == p["repo"])
                self.assertTrue(p["distribution_stopped"])
                for key in ["title", "scope", "changelog", "cover", "latest_release", "downloads", "activity_at"]:
                    self.assertEqual(p[key], old[key])
        self.assertEqual(original, self.records)
    def test_missing_preservation_record_blocks_collection_instead_of_losing_card(self):
        with self.assertRaises(hub.BuildError):
            hub.collect(LibraryClient([], True), self.meta, datetime.now(timezone.utc), library_records=[])
    def test_profile_has_no_private_repository_or_download_links(self):
        data = hub.collect(LibraryClient([], True), self.meta, datetime.now(timezone.utc), library_records=self.records)
        section = hub.readme_section(data).decode("utf-8")
        self.assertIn("작업 기록", section)
        for record in self.records:
            self.assertNotIn("]( <" + record["url"], section)
            self.assertNotIn("](<" + record["url"], section)
            self.assertNotIn("/releases/latest", section)
