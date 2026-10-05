import unittest
from scripts.history import CHIPS, normalize_history, version_key


class HistoryTests(unittest.TestCase):
    def history(self, versions, releases=None, tags=None, dates=None, latest=None):
        if tags is None:
            tags = [{'name': 'v'+v['v']} for v in versions if isinstance(v, dict) and isinstance(v.get('v'), str)] if isinstance(versions, list) else []
        return normalize_history('game', versions, releases or [], tags, dates, latest)

    def test_numeric_sorting_and_version_equivalence(self):
        self.assertEqual(version_key('v1.4.0'), version_key('1.4'))
        scope, log, warnings = self.history([{'v': '1.9', 'added': ['ui']}, {'v': '1.10', 'fixed': ['修正']}, {'v': '1.2', 'added': ['dialogue']}])
        self.assertEqual([e['v'] for e in log], ['1.10', '1.9', '1.2'])
        self.assertEqual(scope['ui'], {'state': 'done', 'since': '1.9'})
        self.assertEqual(scope['dialogue'], {'state': 'done', 'since': None})
        self.assertEqual(warnings, [])

    def test_later_partial_overrides_done_and_nonchip_does_not_affect_scope(self):
        scope, _, _ = self.history([{'v': '1.1', 'partial': ['image'], 'added': ['튜토리얼']}, {'v': '1.0', 'added': ['image']}])
        self.assertEqual(scope['image'], {'state': 'partial', 'since': None})
        self.assertEqual(scope['ui']['state'], 'none')

    def test_partial_becomes_done_at_later_version(self):
        scope, _, _ = self.history([{'v': '1.2', 'improved': ['영상 품질']}, {'v': '1.1', 'added': ['video']}, {'v': '1.0', 'partial': ['video']}])
        self.assertEqual(scope['video'], {'state': 'done', 'since': '1.1'})

    def test_repeated_done_keeps_introduction_version(self):
        scope, _, _ = self.history([{'v': '1.2', 'added': ['video']}, {'v': '1.1', 'added': ['video']}, {'v': '1.0', 'added': ['ui']}])
        self.assertEqual(scope['video']['since'], '1.1')

    def test_no_versions_returns_five_empty_chips(self):
        scope, log, warnings = self.history([])
        self.assertEqual(list(scope), list(CHIPS))
        self.assertTrue(all(v == {'state': 'none', 'since': None} for v in scope.values()))
        self.assertEqual(log, [])
        self.assertEqual(warnings, [])

    def test_three_warnings(self):
        _, _, warnings = self.history([{'v': '1.0'}], tags=[], latest='v2.0')
        self.assertEqual({w['type'] for w in warnings}, {'changelog-missing', 'changelog-orphan', 'changelog-empty-entry'})

    def test_equivalent_latest_and_tag_do_not_warn(self):
        _, log, warnings = self.history([{'v': '1.4', 'fixed': ['修正']}], [{'tag_name': 'v1.4.0', 'html_url': 'https://example.com', 'published_at': '2026-10-01T16:00:00Z'}], [{'name': 'v1.4.0'}], latest='v1.4.0')
        self.assertEqual(warnings, [])
        self.assertEqual(log[0]['date'], '2026-10-02')
        self.assertEqual(log[0]['url'], 'https://example.com')

    def test_date_priority_manual_then_release_then_tag(self):
        releases=[{'tag_name': 'v1.1', 'published_at': '2026-10-02T00:00:00Z'}, {'tag_name': 'v1.2', 'published_at': '2026-10-03T00:00:00Z'}]
        dates={'v1.0': '2026-10-01T16:00:00Z', 'v1.1': '2026-10-01T00:00:00Z', 'v1.2': '2026-10-01T00:00:00Z'}
        _, log, _ = self.history([{'v': '1.0', 'added': ['ui']}, {'v': '1.1', 'fixed': ['修正']}, {'v': '1.2', 'date': '2026-10-04', 'fixed': ['修正']}], releases, dates=dates)
        self.assertEqual([(e['date'], e['date_source']) for e in log], [('2026-10-04', 'manual'), ('2026-10-02', 'release'), ('2026-10-02', 'tag')])

    def test_missing_date_is_blank_and_invalid_date_falls_back(self):
        _, log, warnings = self.history([{'v': '1.0', 'date': 'bad', 'added': ['title']}])
        self.assertEqual(log[0]['date'], '')
        self.assertIn('changelog-invalid', {w['type'] for w in warnings})

    def test_malformed_records_and_duplicate_versions_are_nonfatal(self):
        _, log, warnings = self.history([None, {'v': 'trainer-v1.0'}, {'v': '1.0', 'added': 'bad'}, {'v': '1.0.0', 'added': ['ui']}])
        self.assertEqual(len(log), 1)
        self.assertIn('changelog-invalid', {w['type'] for w in warnings})

    def test_invalid_action_items_are_removed(self):
        _, log, warnings = self.history([{'v': '1.0', 'added': ['ui', 7, '', 'ui']}])
        self.assertEqual(log[0]['added'], ['ui'])
        self.assertIn('changelog-invalid', {w['type'] for w in warnings})
