#!/usr/bin/env python3
"""Tests for reading Z.AI directly from the API.

Run: python3 -m unittest

The main script has no .py extension, so it's loaded via SourceFileLoader.
"""
import importlib.machinery
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

_loader = importlib.machinery.SourceFileLoader(
    'aiusage', str(Path(__file__).parent / 'ai-usage-popup'))
_spec = importlib.util.spec_from_loader('aiusage', _loader)
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)

# Real account response captured on 2026-09-04. `usage` is the limit; `currentValue`, the used amount.
REAL_RESPONSE = {
    "code": 200, "msg": "Operation successful", "success": True,
    "data": {
        "level": "lite",
        "limits": [
            # the weekly one comes FIRST on purpose: the code has to sort by nextResetTime
            {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 10000,
             "currentValue": 44, "remaining": 9955, "percentage": 1,
             "nextResetTime": 1789152613998},
            {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000,
             "currentValue": 44, "remaining": 1955, "percentage": 2,
             "nextResetTime": 1788565955192},
        ],
    },
}


class FakeResponse:
    """Stand-in for urlopen() — context manager with .read(), like the real one."""

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def fake_urlopen(body, captured):
    """Returns a fake urlopen that records in `captured` how it was called."""
    def _fake(req, timeout=None):
        captured['url'] = req.full_url
        captured['method'] = req.get_method()
        captured['headers'] = dict(req.headers)
        captured['timeout'] = timeout
        return FakeResponse(body)
    return _fake


class TestTranslation(unittest.TestCase):
    """zai_info() is a pure function: this is where a wrong number would go unnoticed."""

    def setUp(self):
        self.info = mod.zai_info(REAL_RESPONSE)

    def test_short_window_comes_first(self):
        # the short one becomes the hero number and the card's badge
        self.assertEqual([m['name'] for m in self.info['meters']], ['Session 5h', 'Weekly'])

    def test_order_is_by_duration_and_not_by_reset_time(self):
        """The two criteria agree day to day and diverge at the worst possible moment.

        In the hours before the weekly reset, the weekly window resets BEFORE the 5h one. Sorting
        by reset would make the weekly one (0.4%) the hero and hide the 5h one at 90% — exactly the
        one that's throttling usage.
        """
        payload = json.loads(json.dumps(REAL_RESPONSE))
        weekly, short = payload['data']['limits']
        weekly['nextResetTime'] = 1_700_000_000_000    # resets NOW
        short['nextResetTime'] = 1_800_000_000_000      # resets much later
        short['currentValue'] = 1800                    # and it's the one about to blow past the limit

        meters = mod.zai_info(payload)['meters']
        self.assertEqual(meters[0]['name'], 'Session 5h')
        self.assertAlmostEqual(meters[0]['pct'], 90.0)
        self.assertEqual(mod.klass_of(meters[0]['pct']), 'critical')

    def test_meter_carries_the_formatted_reset(self):
        # without this the card could show "resets in 1788565955192" with the tests green
        for meter in self.info['meters']:
            self.assertRegex(meter['reset'], r'^(\d+[dhm]( \d+[hm])?|now|—)$')

    def test_percentage_comes_from_used_over_limit(self):
        short, weekly = self.info['meters']
        self.assertAlmostEqual(short['pct'], 44 / 2000 * 100)      # 2.2%
        self.assertAlmostEqual(weekly['pct'], 44 / 10000 * 100)    # 0.44%

    def test_does_not_use_the_api_rounded_percentage(self):
        # the API returns percentage=1 for 0.44% — rounded up, erasing the difference
        weekly = self.info['meters'][1]
        self.assertNotEqual(round(weekly['pct']), 1)
        self.assertEqual(mod.fmt_pct(weekly['pct']), '0.4')

    def test_plan_comes_from_level(self):
        self.assertEqual(self.info['plan'], 'GLM Coding Lite')

    def test_credits_in_the_footer(self):
        self.assertEqual(self.info['extras'],
                         ['credits 44/2000 (session 5h) · 44/10000 (weekly)'])

    def test_unknown_unit_degrades_but_still_shows_up(self):
        payload = json.loads(json.dumps(REAL_RESPONSE))
        payload['data']['limits'][0]['unit'] = 99
        names = [m['name'] for m in mod.zai_info(payload)['meters']]
        self.assertIn('Window 1·u99', names)   # shows up with a degraded label
        self.assertEqual(len(names), 2)        # and doesn't disappear from the card

    def test_weeks_plural_when_number_is_not_one(self):
        payload = json.loads(json.dumps(REAL_RESPONSE))
        payload['data']['limits'][0].update({'number': 2, 'usage': 20000})
        names = [m['name'] for m in mod.zai_info(payload)['meters']]
        self.assertIn('2 weeks', names)        # and not "Weekly", which would misstate the period
        self.assertNotIn('Weekly', names)

    def test_success_false_becomes_an_error(self):
        with self.assertRaises(ValueError):
            mod.zai_info({'success': False, 'msg': 'Authentication Failed'})

    def test_response_without_windows_becomes_an_error(self):
        with self.assertRaises(ValueError):
            mod.zai_info({'success': True, 'data': {'level': 'lite', 'limits': []}})

    def test_missing_usage_field_becomes_an_error_and_not_zero_percent(self):
        """If the API renames its fields, the card can't show 0% green: it has to say it failed."""
        for field in ('currentValue', 'usage'):
            with self.subTest(field=field):
                payload = json.loads(json.dumps(REAL_RESPONSE))
                del payload['data']['limits'][0][field]
                with self.assertRaises(ValueError):
                    mod.zai_info(payload)

    def test_non_positive_limit_becomes_an_error(self):
        """`<= 0`, not `== 0`: rejecting only zero would let a negative value become a percentage."""
        for limit in (0, -1, -2000):
            with self.subTest(usage=limit):
                payload = json.loads(json.dumps(REAL_RESPONSE))
                payload['data']['limits'][0]['usage'] = limit   # 0 would render "44/0"
                with self.assertRaises(ValueError):
                    mod.zai_info(payload)

    def test_updated_stays_empty(self):
        # if the local clock were stamped here, another vendor's stale cache would be announced as
        # just-read in the global subtitle — and the suite would stay green
        self.assertEqual(self.info['updated'], '')

    def test_malformed_payload_becomes_an_error(self):
        cases = {
            'body is a list': [],
            'body is a string': 'ok',
            'data has wrong type': {'success': True, 'data': 'lite'},
            'limits has wrong type': {'success': True, 'data': {'limits': 'none'}},
            'limits is empty': {'success': True, 'data': {'limits': []}},
            'window is not an object': {'success': True, 'data': {'limits': ['5h']}},
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    mod.zai_info(payload)


class TestHttpGate(unittest.TestCase):
    """The call needs to carry the Bearer header and the timeout — without them the API refuses."""

    def setUp(self):
        self.captured = {}
        body = json.dumps(REAL_RESPONSE).encode()
        self.patches = [
            mock.patch.object(mod, 'zai_api_key', return_value='test-key'),
            mock.patch.object(mod.urllib.request, 'urlopen',
                              fake_urlopen(body, self.captured)),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_url_method_header_and_timeout(self):
        mod.run_zai()
        self.assertEqual(self.captured['url'], mod.ZAI_URL)
        self.assertEqual(self.captured['method'], 'GET')
        self.assertEqual(self.captured['headers'].get('Authorization'), 'Bearer test-key')
        self.assertEqual(self.captured['timeout'], 15)

    def test_success_envelope(self):
        data = mod.run_zai()
        self.assertEqual(set(data), {'text', 'tooltip', 'class', 'info'})
        self.assertEqual(data['text'], '2.2%')                     # short window
        self.assertEqual(data['class'], mod.klass_of(44 / 2000 * 100))
        self.assertEqual(data['class'], 'low')
        self.assertFalse(mod.is_bad(data))
        self.assertEqual(data['info']['meters'][0]['name'], 'Session 5h')


class TestErrorClasses(unittest.TestCase):
    """The five failure modes go through run_zai() → is_bad() → offline_reason() with the same contract."""

    def _run_with(self, urlopen=None, key='test-key'):
        patches = [mock.patch.object(mod, 'zai_api_key', return_value=key)]
        if urlopen is not None:
            patches.append(mock.patch.object(mod.urllib.request, 'urlopen', urlopen))
        for p in patches:
            p.start()
        try:
            return mod.run_zai()
        finally:
            for p in patches:
                p.stop()

    def _check(self, data, reason_snippet):
        self.assertTrue(mod.is_bad(data), 'error has to land in the "not configured" section')
        self.assertNotIn('info', data, 'an error can\'t carry info — it would become a card with a fake number')
        reason, fix = mod.offline_reason('zai', data)
        self.assertIn(reason_snippet, reason)
        self.assertEqual(fix, '[zai] api_key')
        self.assertLess(len(reason), 60, 'reason has to be short, not the raw traceback')

    def test_no_key(self):
        self._check(self._run_with(key=''), 'no API key')

    def test_timeout(self):
        def blow_up(req, timeout=None):
            raise TimeoutError('took too long')
        self._check(self._run_with(blow_up), 'timed out')

    def test_http_not_200(self):
        def http_error(req, timeout=None):
            raise mod.urllib.error.HTTPError(mod.ZAI_URL, 401, 'Unauthorized', {}, None)
        self._check(self._run_with(http_error), 'HTTP 401')

    def test_body_is_not_json(self):
        def html(req, timeout=None):
            return FakeResponse(b'<html>captive portal</html>')
        self._check(self._run_with(html), 'not JSON')

    def test_success_false(self):
        body = json.dumps({'code': 1000, 'msg': 'Authentication Failed',
                            'success': False}).encode()

        def refused(req, timeout=None):
            return FakeResponse(body)
        self._check(self._run_with(refused), 'API refused')

    def test_network_unavailable_does_not_disguise_itself_as_a_timeout(self):
        # DNS/connection refused is not a timeout: the wrong diagnosis wastes the reader's time
        def no_network(req, timeout=None):
            raise mod.urllib.error.URLError('Name or service not known')
        data = self._run_with(no_network)
        self._check(data, 'network unavailable')
        self.assertNotIn('timed out', data['reason'])


class TestRoutingAndGuard(unittest.TestCase):
    """run_vendor('zai') is the central promise; nothing can escape it."""

    def test_run_vendor_routes_zai_to_the_api(self):
        # without this assertion, changing the condition to 'z.ai' would leave the tests green and
        # the card stuck at "0% · —" via ai-usagebar's subprocess
        with mock.patch.object(mod, 'run_zai', return_value={'text': 'came-from-the-api'}) as api, \
                mock.patch.object(mod.subprocess, 'check_output',
                                  side_effect=AssertionError('must not call ai-usagebar')):
            self.assertEqual(mod.run_vendor('zai'), {'text': 'came-from-the-api'})
        api.assert_called_once_with()

    def test_run_vendor_does_not_let_an_exception_escape(self):
        """An escaping exception kills the pool thread: render never runs and the whole popup freezes."""
        with mock.patch.object(mod, 'run_zai', side_effect=TypeError('unexpected')):
            data = mod.run_vendor('zai')
        self.assertTrue(mod.is_bad(data))
        self.assertIn('TypeError', data['reason'])
        self.assertEqual(mod.offline_reason('zai', data)[1], '[zai] api_key')

    def test_other_vendors_do_not_go_through_the_detour(self):
        with mock.patch.object(mod, 'run_zai', side_effect=AssertionError('wrong detour')), \
                mock.patch.object(mod.subprocess, 'check_output',
                                  return_value='{"text":"x","tooltip":"y","class":"low"}'):
            self.assertEqual(mod.run_vendor('anthropic')['class'], 'low')


class TestFormatting(unittest.TestCase):
    def test_decimal_only_below_ten(self):
        self.assertEqual(mod.fmt_pct(2.2), '2.2')
        self.assertEqual(mod.fmt_pct(0.44), '0.4')
        self.assertEqual(mod.fmt_pct(25), '25')      # integer like the other vendors, unchanged
        self.assertEqual(mod.fmt_pct(23.7), '24')
        self.assertEqual(mod.fmt_pct(0), '0')
        self.assertEqual(mod.fmt_pct(9.96), '10')   # rounding afterwards would give "10.0"

    def test_delta_tolerates_a_missing_timestamp(self):
        # a null nextResetTime used to raise TypeError and freeze every vendor's refresh
        self.assertEqual(mod.fmt_delta(None), '—')
        self.assertEqual(mod.fmt_delta('yesterday'), '—')

    def test_delta_in_the_cards_format(self):
        now = 1788565955.192
        with mock.patch.object(mod.time, 'time', return_value=now):
            self.assertEqual(mod.fmt_delta((now + 4 * 3600 + 31 * 60) * 1000), '4h 31m')
            self.assertEqual(mod.fmt_delta((now + 2 * 86400 + 17 * 3600) * 1000), '2d 17h')
            self.assertEqual(mod.fmt_delta((now + 12 * 60) * 1000), '12m')
            self.assertEqual(mod.fmt_delta((now - 60) * 1000), 'now')


class TestApiKey(unittest.TestCase):
    def test_config_toml_takes_precedence_over_the_env(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as fh:
            fh.write('[zai]\napi_key = "from-config"\n')
            path = Path(fh.name)
        with mock.patch.object(mod, 'ZAI_CONFIG', path), \
                mock.patch.dict(mod.os.environ, {'ZAI_API_KEY': 'from-env'}):
            self.assertEqual(mod.zai_api_key(), 'from-config')
        path.unlink()

    def test_no_config_falls_back_to_the_env(self):
        with mock.patch.object(mod, 'ZAI_CONFIG', Path('/does/not/exist/config.toml')), \
                mock.patch.dict(mod.os.environ, {'ZAI_API_KEY': 'from-env'}):
            self.assertEqual(mod.zai_api_key(), 'from-env')

    def test_zai_as_a_bare_string_in_the_toml_does_not_blow_up(self):
        # `zai = "key"` instead of `[zai]` is a plausible typo
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as fh:
            fh.write('zai = "loose-key"\n')
            path = Path(fh.name)
        with mock.patch.object(mod, 'ZAI_CONFIG', path), \
                mock.patch.dict(mod.os.environ, {'ZAI_API_KEY': 'from-env'}):
            self.assertEqual(mod.zai_api_key(), 'from-env')
        path.unlink()

    def test_nothing_set_returns_empty(self):
        with mock.patch.object(mod, 'ZAI_CONFIG', Path('/does/not/exist/config.toml')), \
                mock.patch.dict(mod.os.environ, {}, clear=True):
            self.assertEqual(mod.zai_api_key(), '')


def _has_display():
    return mod.Gtk.init_check([])[0]


@unittest.skipUnless(_has_display(), 'needs a display (run under Xvfb)')
class TestCard(unittest.TestCase):
    """Widgets require a display; under Xvfb these cases run for real."""

    def setUp(self):
        self.win = mod.UsageWindow.__new__(mod.UsageWindow)

    def test_minimum_cell_lights_up_with_positive_usage(self):
        lit = lambda pct: sum(  # noqa: E731
            1 for c in self.win._cells(pct).get_children()
            if 'on' in c.get_style_context().list_classes()
            or 'tip' in c.get_style_context().list_classes())
        self.assertEqual(lit(0), 0)      # nothing used lights up nothing
        self.assertEqual(lit(2.2), 1)    # 2.2% would light up zero without the rule
        self.assertEqual(lit(0.44), 1)
        self.assertEqual(lit(25), 5)     # 25% still shows 5 cells, as before

    def test_make_card_uses_info_without_reparsing_the_tooltip(self):
        data = {'text': '2.2%', 'tooltip': '', 'class': 'low', 'info': mod.zai_info(REAL_RESPONSE)}
        with mock.patch.object(mod, 'parse_tooltip',
                               side_effect=AssertionError('must not reparse the tooltip')):
            card = self.win.make_card('Z.AI', data)
        texts = []

        def walk(w):
            if isinstance(w, mod.Gtk.Label):
                texts.append(w.get_text())
            if isinstance(w, mod.Gtk.Container):
                for child in w.get_children():
                    walk(child)
        walk(card)
        self.assertIn('Z.AI', texts)
        self.assertIn('GLM Coding Lite', texts)
        self.assertIn('Session 5h', texts)
        self.assertIn('2.2%', texts)


if __name__ == '__main__':
    unittest.main()
