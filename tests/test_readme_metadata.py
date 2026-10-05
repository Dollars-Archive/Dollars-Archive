import unittest
from datetime import datetime, timezone

from scripts.readme_metadata import HEADINGS, merge_scope, parse_readme
from scripts.build_hub import collect


def form(info=None, statuses=None):
    info = info or {'원제': '原題', '플랫폼': 'PC (Steam) / Nintendo Switch', '개발사': '개발',
                    '장르': 'RPG', '플레이타임': '10–20시간', '일본 발매일': '2020년 2월 27일'}
    statuses = statuses or {key: '미작업' for key in HEADINGS}
    text = '# 새 게임 한국어 패치\n<!-- kr-patch:game-info:v1:start -->\n## 게임 정보\n'
    text += '| 항목 | 내용 |\n| --- | --- |\n'
    text += ''.join(f'| {key} | {value} |\n' for key, value in info.items())
    text += '<!-- kr-patch:game-info:v1:end -->\n<!-- kr-patch:scope:v1:start -->\n'
    text += ''.join(f'## {heading}\n\n상태: {statuses[key]}\n\n' for key, heading in HEADINGS.items())
    return text + '<!-- kr-patch:scope:v1:end -->\n'


class ReadmeTests(unittest.TestCase):
    def test_dates_platforms_and_title(self):
        meta, scope, warnings = parse_readme('new', form())
        self.assertEqual(meta['title'], '새 게임')
        self.assertEqual(meta['release_jp'], '2020-02-27')
        self.assertEqual(meta['platforms'], ['PC', 'Switch'])
        self.assertEqual(len(scope), 5)
        self.assertFalse(warnings)

    def test_explicit_statuses_and_unknown_are_not_inferred_from_screenshots(self):
        text = form(statuses=dict(zip(HEADINGS, ['완료','일부','미작업','해당 없음','확인 필요'])))
        _,scope,warnings = parse_readme('new',text.replace('상태: 미작업','상태: 미작업\n<img src="translated.png">'))
        self.assertEqual([s['state'] for s in scope.values()], ['done','partial','none','none','none'])
        self.assertEqual(scope['image']['status'], '해당 없음')
        self.assertEqual(len(warnings),1)

    def test_duplicate_or_missing_markers_do_not_read_unrelated_tables(self):
        text = form()
        for broken in [text.replace('<!-- kr-patch:game-info:v1:end -->',''),
                       '<!-- kr-patch:game-info:v1:start -->'+text]:
            meta,_,warnings = parse_readme('new',broken)
            self.assertEqual(meta,{})
            self.assertTrue(warnings)
        self.assertEqual(parse_readme('old','# Legacy\n| 개발사 | X |'), ({},{},[]))

    def test_wrong_dates_fall_back_and_empty_fields_can_be_cleared(self):
        text = form().replace('2020년 2월 27일','2020-02-31').replace('| 개발사 | 개발 |','| 개발사 | — |')
        meta,_,warnings = parse_readme('new',text)
        self.assertNotIn('release_jp',meta)
        self.assertEqual(meta['developer'],'')
        self.assertEqual(len(warnings),2)

    def test_escaped_pipes_and_formatted_ids(self):
        meta,_,warnings = parse_readme('new',form().replace('| 장르 | RPG |',r'| 장르 | RPG \| ADV |')+'')
        self.assertEqual(meta['genre'],'RPG | ADV')
        self.assertFalse(warnings)
        meta,_,_ = parse_readme('new',form().replace('| 장르 | RPG |','| 장르 | RPG |\n| Title ID | `0100012345678900` |'))
        self.assertEqual(meta['product_id'],'0100012345678900')

    def test_invalid_scope_preserves_history_and_clearing_drops_since(self):
        _,scope,warnings = parse_readme('new',form().replace('상태: 미작업','상태: 아무거나',1))
        historical = {key:{'state':'done','since':'1.1'} for key in HEADINGS}
        merged = merge_scope(historical,scope)
        self.assertEqual(merged['title'],historical['title'])
        self.assertEqual(merged['ui']['state'],'none')
        self.assertIsNone(merged['ui']['since'])
        self.assertEqual(len(warnings),1)

    def test_new_topic_repo_needs_no_central_game_info_and_wip_can_show_done(self):
        class Client:
            def repositories(self): return [{'name':'new','topics':['kr-patch'],'description':'old description',
                'pushed_at':'2026-10-05T00:00:00Z','html_url':'https://github.com/Dollars-Archive/new'}]
            def readme(self,name): return form(statuses={key:'완료' for key in HEADINGS})
            def releases(self,name): return []
            def tags(self,name): return []
        data = collect(Client(),{},datetime(2026,10,5,tzinfo=timezone.utc),lambda u:404)
        patch = data['patches'][0]
        self.assertEqual(patch['title'],'새 게임')
        self.assertEqual(patch['developer'],'개발')
        self.assertEqual(patch['status'],'wip')
        self.assertEqual(patch['scope']['title']['state'],'done')
        self.assertFalse(any(w['type']=='missing-metadata' for w in data['warnings']))

    def test_readme_overrides_stale_central_facts_but_keeps_history(self):
        from test_build_hub import FixtureClient, NOW
        text = form(statuses={key:'완료' for key in HEADINGS})
        data = collect(FixtureClient(readme=text),{'sample-kr-patch':{
            'developer':'stale','platforms':['PS2'],'versions':[{'v':'1.0','added':['ui']}]}},NOW,lambda u:404)
        patch = data['patches'][0]
        self.assertEqual(patch['developer'],'개발')
        self.assertEqual(patch['platforms'],['PC','Switch'])
        self.assertEqual(patch['changelog'][0]['added'],['ui'])


if __name__ == '__main__': unittest.main()
