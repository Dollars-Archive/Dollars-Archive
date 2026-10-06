import unittest
from datetime import timedelta
from unittest.mock import Mock

from scripts import build_hub as hub
from test_build_hub import FixtureClient, NOW, repo, release


class ActivityTests(unittest.TestCase):
    def test_unreleased_games_follow_released_games_despite_newer_work(self):
        class Client(FixtureClient):
            def releases(self,name):
                return [release()] if name.startswith('released') else []
            def tags(self,name):
                return []
        repos=[repo('unreleased-new',pushed_at='2026-10-04T00:00:00Z'),
               repo('released-old',pushed_at='2026-10-01T00:00:00Z'),
               repo('unreleased-old',pushed_at='2026-10-03T00:00:00Z'),
               repo('released-new',pushed_at='2026-10-02T00:00:00Z')]
        data=hub.collect(Client(repositories=repos),{},NOW,lambda u:404)
        self.assertEqual([p['repo'] for p in data['patches']],
                         ['released-new','released-old','unreleased-new','unreleased-old'])
        section=hub.readme_section(data).decode('utf-8')
        self.assertLess(section.index('released-old>'),section.index('unreleased-new>'))

    def test_first_release_moves_a_game_out_of_the_unreleased_group(self):
        class Client(FixtureClient):
            def releases(self,name):
                return [release()] if name=='old' or self.publish_new else []
            def tags(self,name):
                return []
        client=Client(repositories=[repo('new',pushed_at='2026-10-04T00:00:00Z'),repo('old')])
        client.publish_new=False
        self.assertEqual([p['repo'] for p in hub.collect(client,{},NOW,lambda u:404)['patches']],['old','new'])
        client.publish_new=True
        self.assertEqual([p['repo'] for p in hub.collect(client,{},NOW,lambda u:404)['patches']],['new','old'])

    def client(self):
        client = hub.GitHubClient()
        client.activity_exclusions = {'sample-kr-patch':{
            'commit':'maintenance', 'ignored_pushed_at':'2026-10-05T00:00:00Z',
            'previous_activity_at':'2026-09-30T00:00:00Z'}}
        return client

    def test_exact_maintenance_push_uses_backed_up_date(self):
        client = self.client()
        client.get = Mock(return_value=([{'sha':'maintenance'}],None))
        self.assertEqual(client.activity_date(repo(pushed_at='2026-10-05T00:00:00Z')),'2026-09-30T00:00:00Z')

    def test_next_push_including_tags_is_not_frozen(self):
        client = self.client()
        client.get = Mock()
        value = '2026-10-06T00:00:00Z'
        self.assertEqual(client.activity_date(repo(pushed_at=value)),value)
        client.get.assert_not_called()

    def test_a_different_commit_at_the_same_timestamp_is_not_excluded(self):
        client = self.client()
        client.get = Mock(return_value=([{'sha':'real-work'}],None))
        value = '2026-10-05T00:00:00Z'
        self.assertEqual(client.activity_date(repo(pushed_at=value)),value)

    def test_restored_activity_orders_latest_first_and_new_release_counts(self):
        class Client(FixtureClient):
            def activity_date(self,item):
                return {'a':'2026-10-01T00:00:00Z','b':'2026-09-20T00:00:00Z'}[item['name']]
        repos = [repo('a',pushed_at='2026-10-05T00:00:00Z'),repo('b',pushed_at='2026-10-05T00:01:00Z')]
        data = hub.collect(Client(repositories=repos,releases=[]),{},NOW,lambda u:404)
        self.assertEqual([p['repo'] for p in data['patches']],['a','b'])
        data = hub.collect(Client(repositories=repos,releases=[release(published_at='2026-10-03T00:00:00Z')]),{},NOW,lambda u:404)
        self.assertTrue(all(p['activity_at']=='2026-10-03T00:00:00Z' for p in data['patches']))

    def test_wip_staleness_uses_activity_not_bulk_readme_push(self):
        class Client(FixtureClient):
            def activity_date(self,item): return (NOW-timedelta(days=31)).isoformat()
        data = hub.collect(Client(releases=[]),{},NOW,lambda u:404)
        self.assertTrue(any(w['type']=='wip-stale' for w in data['warnings']))
