import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image
from scripts import covers
from scripts import build_hub as hub

PAGE = 'https://gamesdb.launchbox-app.com/games/details/123-example'
IMAGE = 'https://images.launchbox-app.com/front.jpg'


def front(region='Japan', kind='Box - Front', url=IMAGE):
    return f'<img alt="Game - {kind} ({region}) - 800x1000" src="{url}">'


def picture():
    out = io.BytesIO()
    Image.new('RGB', (800, 1000), '#324567').save(out, 'PNG')
    return out.getvalue()


def catalogue():
    return {'generated_at': '2026-10-04T12:00:00Z', 'patches': [{'repo': 'example'}], 'warnings': []}


class CoverTests(unittest.TestCase):
    def test_launchbox_html_fixture(self):
        page = (Path(__file__).parent / 'fixtures/launchbox-fronts.html').read_text(encoding='utf-8')
        self.assertEqual(covers.parse_front_cover(page)['source_image'], 'https://images.launchbox-app.com/japan.jpg')

    def test_japan_front_priority_and_no_screenshot_or_reconstruction(self):
        candidate = covers.parse_front_cover(front('North America') + front(kind='Screenshot - Game Title') + front(kind='Box - Front - Reconstructed') + front(url=IMAGE + '?japan'))
        self.assertEqual(candidate['source_image'], IMAGE + '?japan')
        self.assertEqual(candidate['region'], 'Japan')
        self.assertIsNone(covers.parse_front_cover(front(kind='Screenshot - Game Title')))
        self.assertIsNone(covers.parse_front_cover(front(kind='Box - Front - Reconstructed')))

    def test_region_fallback_is_front_only(self):
        self.assertEqual(covers.parse_front_cover(front('North America'))['region'], 'North America')
        self.assertIsNone(covers.parse_front_cover('<html>changed markup</html>'))
        self.assertIsNone(covers.parse_front_cover(front(url='https://other.example/front.jpg')))

    def test_resize_preserves_ratio(self):
        with Image.open(io.BytesIO(covers.thumbnail(picture()))) as image:
            self.assertEqual(image.size, (320, 400))
            self.assertEqual(image.format, 'WEBP')

    def test_cache_and_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fetch = Mock(side_effect=[front().encode(), picture()])
            data = catalogue()
            outputs = covers.plan_covers(root, data, {'example': {'launchbox_url': PAGE}}, fetch=fetch)
            self.assertEqual(fetch.call_count, 2)
            self.assertFalse((root / 'docs/covers/example.webp').exists())
            hub.apply_outputs(outputs)
            forbidden = Mock(side_effect=AssertionError('cached covers must not fetch'))
            second = catalogue()
            second['generated_at'] = '2026-10-05T12:00:00Z'
            again = covers.plan_covers(root, second, {'example': {'launchbox_url': PAGE}}, fetch=forbidden)
            forbidden.assert_not_called()
            self.assertEqual(hub.apply_outputs(again), [])
            self.assertEqual(second['patches'][0]['cover'], 'covers/example.webp')
            self.assertEqual(second['patches'][0]['cover_revision'], data['patches'][0]['cover_revision'])
            self.assertEqual(json.loads(next(iter(again.values())))['example']['fetched_at'], data['generated_at'])
            refreshed = Mock(side_effect=[front().encode(), picture()])
            covers.plan_covers(root, catalogue(), {'example': {'launchbox_url': PAGE}}, refresh=True, fetch=refreshed)
            self.assertEqual(refreshed.call_count, 2)

    def test_replaced_cover_changes_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = catalogue()
            hub.apply_outputs(covers.plan_covers(root, first, {'example': {'cover': IMAGE}}, fetch=Mock(return_value=picture())))
            buffer = io.BytesIO()
            Image.new('RGB', (300, 400), '#d4b567').save(buffer, 'PNG')
            second = catalogue()
            covers.plan_covers(root, second, {'example': {'cover': IMAGE + '?new'}}, fetch=Mock(return_value=buffer.getvalue()))
            self.assertNotEqual(first['patches'][0]['cover_revision'], second['patches'][0]['cover_revision'])

    def test_manual_file_skips_launchbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'docs/covers/manual.png'
            path.parent.mkdir(parents=True)
            path.write_bytes(picture())
            fetch = Mock(side_effect=AssertionError('manual file must not fetch'))
            data = catalogue()
            outputs = covers.plan_covers(root, data, {'example': {'cover': 'docs/covers/manual.png', 'launchbox_url': PAGE}}, fetch=fetch)
            fetch.assert_not_called()
            self.assertIn(root / 'docs/covers/example.webp', outputs)
            self.assertEqual(data['warnings'], [])

    def test_failure_nonfatal_and_missing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            data = catalogue()
            covers.plan_covers(Path(directory), data, {'example': {'launchbox_url': PAGE}}, fetch=Mock(side_effect=TimeoutError))
            self.assertIsNone(data['patches'][0]['cover'])
            self.assertEqual(data['warnings'][0]['type'], 'cover-fetch-failed')
            data = catalogue()
            fetch = Mock()
            covers.plan_covers(Path(directory), data, {}, fetch=fetch)
            fetch.assert_not_called()
            self.assertEqual(data['warnings'][0]['type'], 'missing-launchbox')

    def test_source_change_invalidates_cache_and_failed_refresh_retains_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            meta = {'example': {'launchbox_url': PAGE}}
            hub.apply_outputs(covers.plan_covers(root, catalogue(), meta, fetch=Mock(side_effect=[front().encode(), picture()])))
            data = catalogue()
            covers.plan_covers(root, data, meta, refresh=True, fetch=Mock(side_effect=TimeoutError))
            self.assertEqual(data['patches'][0]['cover'], 'covers/example.webp')
            data = catalogue()
            covers.plan_covers(root, data, {'example': {'launchbox_url': PAGE + '-new'}}, fetch=Mock(side_effect=TimeoutError))
            self.assertIsNone(data['patches'][0]['cover'])


if __name__ == '__main__':
    unittest.main()
