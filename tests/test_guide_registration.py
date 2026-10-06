import importlib.util
import unittest
from pathlib import Path
from scripts import build_hub as hub
from test_build_hub import FixtureClient, NOW

spec = importlib.util.spec_from_file_location("guide_link", Path(__file__).parents[1] / "templates/ensure_guide_registration.py")
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)

class GuideRegistrationTests(unittest.TestCase):
    def test_preserves_unicode_images_and_crlf_and_is_idempotent(self):
        original = "# 새 게임\r\n\r\n![그림](images/a.png)\r\n설치 안내 및 상태 주석\r\n"
        result = link.ensure_link(original, "Dollars-Archive/new-kr-patch")
        self.assertIn("patch_repo: new-kr-patch", result)
        self.assertTrue(result.startswith('# 새 게임\r\n'))
        self.assertTrue(result.endswith(original.split('\r\n', 1)[1]))
        self.assertEqual(result.replace("\r\n", "").count("\n"), 0)
        self.assertEqual(link.ensure_link(result, "Dollars-Archive/new-kr-patch"), result)

    def test_incomplete_marker_and_other_owner_are_rejected(self):
        with self.assertRaises(ValueError):
            link.ensure_link("# Game\n" + link.START, "Dollars-Archive/sample")
        with self.assertRaises(ValueError):
            link.ensure_link("# Game\n", "AnotherOwner/sample")

    def test_hub_detects_only_missing_registration_link(self):
        missing = hub.collect(FixtureClient(), {}, NOW, lambda u: 404)
        present = hub.collect(FixtureClient(readme=link.ensure_link("# Game\n", "Dollars-Archive/sample-kr-patch")), {}, NOW, lambda u: 404)
        self.assertIn("walkthrough-registration-missing", {w["type"] for w in missing["warnings"]})
        self.assertNotIn("walkthrough-registration-missing", {w["type"] for w in present["warnings"]})

    def test_template_repository_is_resolved_and_wrong_mapping_is_rejected(self):
        template = (Path(__file__).parents[1] / 'templates/README.template.md').read_text(encoding='utf-8')
        result = link.ensure_link(template, 'Dollars-Archive/new-kr-patch')
        self.assertIn('patch_repo: new-kr-patch', result)
        self.assertEqual(result.count(link.START), 1)
        with self.assertRaises(ValueError):
            link.ensure_link(result, 'Dollars-Archive/another-game')

    def test_registration_stays_hidden_and_actual_walkthrough_survives(self):
        source = '# 게임\r\n\r\n![사진](images/a.png)\r\n'
        source += '[직접 만든 공략집 등록 안내](' + link.URL + ') · [공략집 모음](https://example.com/guide)\r\n'
        result = link.ensure_link(source, 'Dollars-Archive/sample-kr-patch')
        visible = link.re.sub(r'<!--.*?-->', '', result, flags=link.re.S)
        self.assertNotIn(link.URL, visible)
        self.assertIn('[공략집 모음](https://example.com/guide)', visible)
        self.assertIn('![사진](images/a.png)', visible)
        self.assertIn(link.URL, result)
        self.assertEqual(result, link.ensure_link(result, 'Dollars-Archive/sample-kr-patch'))
        self.assertNotIn('\n', result.replace('\r\n',''))

    def test_existing_hidden_marker_does_not_preserve_public_notice(self):
        source = link.ensure_link('# 게임\n', 'Dollars-Archive/sample-kr-patch')
        source += '[직접 만든 공략집 등록 안내](' + link.URL + ')\n'
        result = link.ensure_link(source, 'Dollars-Archive/sample-kr-patch')
        self.assertNotIn(link.URL, link.re.sub(r'<!--.*?-->', '', result, flags=link.re.S))
        self.assertEqual(result, link.ensure_link(result, 'Dollars-Archive/sample-kr-patch'))

    def test_html_registration_link_removed_without_changing_comment(self):
        source = '<!-- instructions: ' + link.URL + ' -->\n<a href="' + link.URL + '">등록 안내</a>\n'
        result = link.remove_visible_registration(source)
        self.assertEqual(result, '<!-- instructions: ' + link.URL + ' -->\n')
