import tempfile
import unittest
from pathlib import Path

from scripts import downloads
from scripts import build_hub as hub


def catalogue(count=10, asset_id=1):
    return [{'repo': 'game', 'assets': [{'tag': 'v1.0', 'name': 'patch.zip', 'asset_id': asset_id, 'downloads': count}]}]


class DownloadTests(unittest.TestCase):
    def test_late_asset_warning_boundary(self):
        patch = {'repo': 'game', 'status': 'released', 'latest_release': None, 'guide_url': '', 'description': 'game', 'assets': [{'created_at': '2026-10-02T00:00:01Z', 'release_published_at': '2026-10-01T00:00:00Z'}]}
        warnings = hub.patch_warnings(patch, '[release](https://github.com/a/b/releases)', True, hub.iso_time('2026-10-04T00:00:00Z'))
        self.assertIn('asset-reuploaded', [w['type'] for w in warnings])
        patch['assets'][0]['created_at'] = '2026-10-02T00:00:00Z'
        self.assertNotIn('asset-reuploaded', [w['type'] for w in hub.patch_warnings(patch, '[release](https://github.com/a/b/releases)', True, hub.iso_time('2026-10-04T00:00:00Z'))])

    def first(self):
        return downloads.update_ledger({}, catalogue(), '2026-10-04T13:00:00Z')

    def total(self, ledger):
        return sum(a['carried'] + a['last_count'] for a in ledger['assets'].values())

    def test_reupload_preserves_previous_count(self):
        first = self.first()
        second = downloads.update_ledger(first, catalogue(3, 2), 'later')
        self.assertEqual(self.total(second), 13)
        self.assertEqual(second['started_at'], first['started_at'])
        self.assertEqual(self.total(first), 10)
        self.assertEqual(downloads.update_ledger(second, catalogue(3, 2), 'later'), second)

    def test_counter_decrease_preserves_previous_count(self):
        second = downloads.update_ledger(self.first(), catalogue(2), 'later')
        self.assertEqual(self.total(second), 12)
        third = downloads.update_ledger(second, catalogue(4), 'later')
        self.assertEqual(self.total(third), 14)

    def test_removed_release_and_reappearance(self):
        removed = downloads.update_ledger(self.first(), [{'repo': 'game', 'assets': []}], 'later')
        self.assertEqual(self.total(removed), 10)
        self.assertTrue(next(iter(removed['assets'].values()))['removed'])
        self.assertEqual(downloads.update_ledger(removed, [], 'later'), removed)
        returned = downloads.update_ledger(removed, catalogue(15), 'later')
        self.assertEqual(self.total(returned), 15)
        self.assertFalse(next(iter(returned['assets'].values()))['removed'])

    def test_output_totals_and_unchanged_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {'generated_at': '2026-10-04T13:00:00Z', 'patches': catalogue(), 'summary': {}}
            hub.apply_outputs(downloads.plan_downloads(root, data))
            data['patches'] = catalogue(3, 2)
            hub.apply_outputs(downloads.plan_downloads(root, data))
            self.assertEqual(data['patches'][0]['downloads_current'], 3)
            self.assertEqual(data['patches'][0]['downloads_carried'], 10)
            self.assertEqual(data['summary']['downloads'], 13)
            # Supply raw API counts again, not the derived total.
            data['patches'] = catalogue(3, 2)
            self.assertEqual(hub.apply_outputs(downloads.plan_downloads(root, data)), [])
            data['patches'] = [{'repo': 'game', 'assets': []}]
            downloads.plan_downloads(root, data)
            self.assertEqual(data['patches'][0]['downloads'], 13)

    def test_one_download_changes_readme_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {'generated_at': '2026-10-04T13:00:00Z', 'summary': {'total': 0, 'released': 0, 'wip': 0, 'downloads': 10}, 'patches': [], 'related': []}
            hub.apply_outputs(hub.planned_outputs(root, data))
            data['summary']['downloads'] += 1
            outputs = hub.planned_outputs(root, data)
            self.assertNotEqual(outputs[root/'README.md'], (root/'README.md').read_bytes())
            self.assertNotEqual(outputs[root/'docs/data/patches.json'], (root/'docs/data/patches.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
