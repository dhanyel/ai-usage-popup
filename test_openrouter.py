#!/usr/bin/env python3
"""Tests for the OpenRouter card, which is measured in money rather than time windows.

Run: python3 -m unittest
"""
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_loader = importlib.machinery.SourceFileLoader(
    'aiusage', str(Path(__file__).parent / 'ai-usage-popup'))
_spec = importlib.util.spec_from_loader('aiusage', _loader)
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)

# Real tooltip captured from `ai-usagebar --vendor openrouter --json` on 2026-10-05, after
# strip_markup(). The first line carries a fragment of the API key on purpose: the parser must
# never copy it into the card.
TOOLTIP = '\n'.join([
    'OpenRouter — sk-or-v1-aec...212',
    'Balance',
    '░░░░░░░░░░░░░░░░░░░░ $9.86',
    '$0.14 of $10.00 used (1%)',
    'Usage',
    'today $0.14 · week $0.14 · month $0.14',
    'Per-key limit',
    '$49.86 of $50.00 remaining',
    'paid tier',
    'Updated 18:32',
])


class TestParsing(unittest.TestCase):
    def setUp(self):
        self.info = mod.openrouter_info(TOOLTIP)

    def test_both_money_meters_are_built(self):
        self.assertEqual([m['name'] for m in self.info['meters']],
                         ['Balance', 'Per-key limit'])

    def test_order_comes_from_the_amounts_not_from_the_tooltip_order(self):
        """The order must not depend on the line order the binary happens to emit."""
        swapped = '\n'.join([
            'OpenRouter — sk-or-v1-aec...212',
            'Per-key limit', '$49.86 of $50.00 remaining',
            'Balance', '░░░ $9.86', '$0.14 of $10.00 used (1%)',
        ])
        self.assertEqual([m['name'] for m in mod.openrouter_info(swapped)['meters']],
                         ['Balance', 'Per-key limit'])

    def test_the_hero_is_the_limit_that_binds_not_the_smaller_pot(self):
        """Sorting by pot size headlines the wrong number in the case that matters.

        A $10 balance barely touched next to a $50 per-key cap at 96%: the cap is what starts
        refusing requests, and a card that headlines the green one is worse than no card.
        """
        tight = '\n'.join([
            'OpenRouter — sk-or-v1-aec...212',
            'Balance', '$0.14 of $10.00 used (1%)',
            'Per-key limit', '$2.00 of $50.00 remaining',
        ])
        meters = mod.openrouter_info(tight)['meters']
        self.assertEqual(meters[0]['name'], 'Per-key limit')
        self.assertEqual(mod.klass_of(meters[0]['pct']), 'critical')

    def test_percentage_comes_from_the_dollars_not_the_rounded_label(self):
        # the tooltip rounds 1.4% down to "(1%)"; reading that label would lose the difference
        balance = self.info['meters'][0]
        self.assertAlmostEqual(balance['pct'], 0.14 / 10.00 * 100)
        self.assertNotEqual(round(balance['pct']), balance['pct'])

    def test_remaining_is_not_read_as_used(self):
        """"$49.86 of $50.00 remaining" means 0.28% spent, not 99.7%.

        Getting this backwards paints a nearly-full red gauge on an almost untouched key — a
        plausible number, which is the worst kind of wrong.
        """
        per_key = self.info['meters'][1]
        self.assertAlmostEqual(per_key['pct'], (50.00 - 49.86) / 50.00 * 100, places=6)
        self.assertLess(per_key['pct'], 1)
        self.assertEqual(mod.klass_of(per_key['pct']), 'low')

    def test_each_meter_says_how_much_money_is_left(self):
        # there is no reset for a balance; "left" is the equivalent information
        self.assertEqual(self.info['meters'][0]['note'], '$9.86 left')
        self.assertEqual(self.info['meters'][1]['note'], '$49.86 left')

    def test_plan_is_the_tier_and_never_the_key(self):
        self.assertEqual(self.info['plan'], 'paid tier')
        rendered = repr(self.info)
        for leak in ('sk-or', 'aec...212'):
            self.assertNotIn(leak, rendered, 'key fragment leaked into the card')

    def test_footer_carries_the_usage_window(self):
        self.assertEqual(self.info['extras'], ['today $0.14 · week $0.14 · month $0.14'])

    def test_updated_is_picked_up(self):
        self.assertEqual(self.info['updated'], '18:32')


class TestKeyNeverReachesTheScreen(unittest.TestCase):
    """The guard is by content, not by line number — one extra line must not reopen the leak."""

    def test_a_key_outside_line_zero_is_redacted_from_the_meter_name(self):
        shifted = '\n'.join([
            'AI Usage',
            'OpenRouter — sk-or-v1-aec...212',
            '$0.14 of $10.00 used (1%)',
        ])
        name = mod.openrouter_info(shifted)['meters'][0]['name']
        self.assertNotIn('sk-or-v1-aec', name)
        self.assertIn('sk-…', name)

    def test_offline_row_redacts_the_key_too(self):
        """make_card was hardened; offline_reason is the sibling renderer of the same line."""
        reason, fix = mod.offline_reason('openrouter', {'text': '⚠', 'tooltip': TOOLTIP})
        self.assertNotIn('sk-or-v1-aec', reason)
        self.assertIn('sk-…', reason)

    def test_redaction_leaves_ordinary_text_alone(self):
        self.assertEqual(mod.redact_keys('paid tier · $9.86 left'), 'paid tier · $9.86 left')


class TestTierWord(unittest.TestCase):
    def test_frontier_is_not_a_tier(self):
        """"frontier models" is OpenRouter's own vocabulary; a loose substring broke two fields."""
        tooltip = '\n'.join([
            'OpenRouter — sk-or-v1-aec...212',
            'frontier models',
            '$0.14 of $10.00 used (1%)',
            'paid tier',
        ])
        info = mod.openrouter_info(tooltip)
        self.assertEqual(info['plan'], 'paid tier')
        self.assertEqual(info['meters'][0]['name'], 'frontier models')


class TestPartialParse(unittest.TestCase):
    def test_one_unreadable_line_does_not_discard_the_good_meters(self):
        tooltip = '\n'.join([
            'OpenRouter — sk-or-v1-aec...212',
            'Balance', '$0.14 of $10.00 used (1%)',
            'Per-key limit', '$4..0 of $50.00 remaining',
            'today $0.14 · week $0.14 · month $0.14',
        ])
        info = mod.openrouter_info(tooltip)
        self.assertEqual([m['name'] for m in info['meters']], ['Balance'])
        self.assertEqual(info['extras'], ['today $0.14 · week $0.14 · month $0.14'])

    def test_a_credit_floors_the_gauge_instead_of_going_backwards(self):
        # "$-5.00 ... used" means money came back; a bar cannot be less than empty
        tooltip = 'OpenRouter — sk\nBalance\n$-5.00 of $10.00 used (0%)'
        meter = mod.openrouter_info(tooltip)['meters'][0]
        self.assertEqual(meter['pct'], 0.0)
        self.assertEqual(meter['note'], '$15.00 left')


class TestOverdrawn(unittest.TestCase):
    """A negative balance must show as a full red gauge, not disappear."""

    TOOLTIP = '\n'.join([
        'OpenRouter — sk-or-v1-aec...212',
        'Balance', '$-5.00 of $10.00 remaining',
        'paid tier',
    ])

    def test_the_meter_still_exists(self):
        # without the optional minus in the regex the line is read as a label and the meter is
        # simply gone — an overdrawn account rendering as a healthy card with one gauge fewer
        meters = mod.openrouter_info(self.TOOLTIP)['meters']
        self.assertEqual([m['name'] for m in meters], ['Balance'])

    def test_it_reads_as_over_the_limit(self):
        meter = mod.openrouter_info(self.TOOLTIP)['meters'][0]
        self.assertGreater(meter['pct'], 100)
        self.assertEqual(mod.klass_of(meter['pct']), 'critical')
        self.assertEqual(meter['note'], '$-5.00 left')


class TestFallback(unittest.TestCase):
    """An unparseable tooltip must lose detail — never invent a number, never leak the key."""

    UNPARSEABLE = 'OpenRouter — sk-or-v1-aec...212\nBalance\n$1..0 of $10.00 used (1%)\npaid tier'

    def test_returns_none_when_there_are_no_money_lines(self):
        self.assertIsNone(mod.openrouter_info('OpenRouter — sk-or-v1-aec...212\nsomething else'))

    def test_returns_none_on_a_zero_total(self):
        self.assertIsNone(mod.openrouter_info('OpenRouter\nBalance\n$0.00 of $0.00 used (0%)'))

    def _run_with(self, tooltip):
        payload = __import__('json').dumps({'text': '$9.86', 'tooltip': tooltip, 'class': 'low'})
        with mock.patch.object(mod.subprocess, 'check_output', return_value=payload):
            return mod.run_vendor('openrouter')

    def test_degraded_card_keeps_the_vendor_alive(self):
        data = self._run_with(self.UNPARSEABLE)
        self.assertFalse(mod.is_bad(data))              # a working account is not "unavailable"
        self.assertEqual(data['info']['meters'], [])    # it just loses the gauges

    def test_degraded_card_still_never_shows_the_key(self):
        """The fallback is where the leak came back: parse_tooltip() reads the title as the plan.

        With the title being "OpenRouter — sk-or-v1-aec...212", falling back there puts a
        fragment of the API key straight into the plan pill.
        """
        data = self._run_with(self.UNPARSEABLE)
        self.assertEqual(data['info']['plan'], 'paid tier')
        self.assertNotIn('sk-or', repr(data['info']))

    def test_degraded_card_without_a_tier_line_shows_no_plan_at_all(self):
        data = self._run_with('OpenRouter — sk-or-v1-aec...212\nnothing parseable')
        self.assertEqual(data['info']['plan'], '')
        self.assertNotIn('sk-or', repr(data['info']))

    def test_a_parser_crash_does_not_kill_the_vendor_nor_leak(self):
        payload = ('{"text":"$9.86","tooltip":"OpenRouter — sk-or-v1-aec...212\\npaid tier",'
                   '"class":"low"}')
        with mock.patch.object(mod.subprocess, 'check_output', return_value=payload), \
                mock.patch.object(mod, 'openrouter_info', side_effect=ValueError('boom')):
            data = mod.run_vendor('openrouter')
        self.assertFalse(mod.is_bad(data))
        self.assertNotIn('sk-or', repr(data['info']))


class TestRouting(unittest.TestCase):
    def test_run_vendor_attaches_info_for_openrouter(self):
        payload = ('{"text":"$9.86 · $0.14","tooltip":%s,"class":"low"}'
                   % __import__('json').dumps(TOOLTIP))
        with mock.patch.object(mod.subprocess, 'check_output', return_value=payload):
            data = mod.run_vendor('openrouter')
        self.assertIn('info', data)
        self.assertEqual(data['info']['plan'], 'paid tier')

    def test_other_vendors_are_untouched(self):
        payload = '{"text":"x","tooltip":"Anthropic\\nSession","class":"low"}'
        with mock.patch.object(mod.subprocess, 'check_output', return_value=payload):
            data = mod.run_vendor('anthropic')
        self.assertNotIn('info', data)


class TestEveryTooltipFieldIsRedacted(unittest.TestCase):
    """The docstring on redact_keys() claims full coverage; these pin it to every field.

    The installed binary cannot put a key in the footer, the timestamp or the fallback text — but
    the guard is written as a promise about any line, so it has to hold for any line.
    """

    LEAKY = '\n'.join([
        'OpenRouter — sk-or-v1-aec...212',
        'Balance', '$0.14 of $10.00 used (1%)',
        'today $0.14 · week sk-or-v1-leaked999 · month $0.14',
        'Updated sk-or-v1-leaked999',
    ])

    def setUp(self):
        self.info = mod.openrouter_info(self.LEAKY)

    def test_footer(self):
        self.assertNotIn('leaked999', self.info['extras'][0])

    def test_timestamp(self):
        self.assertNotIn('leaked999', self.info['updated'])

    def test_whole_info(self):
        self.assertNotIn('sk-or-v1-', repr(self.info))


class TestEmptyPot(unittest.TestCase):
    def test_a_zero_pot_degrades_instead_of_dividing_by_zero(self):
        # there is no percentage of $0.00; the card drops to text rather than inventing one
        self.assertIsNone(mod.openrouter_info('OpenRouter\nBalance\n$0.00 of $0.00 used (0%)'))


def _has_display():
    return mod.Gtk.init_check([])[0]


@unittest.skipUnless(_has_display(), 'needs a display (run under Xvfb)')
class TestCard(unittest.TestCase):
    def setUp(self):
        self.win = mod.UsageWindow.__new__(mod.UsageWindow)

    def _labels(self, widget, out=None):
        out = [] if out is None else out
        if isinstance(widget, mod.Gtk.Label):
            out.append(widget.get_text())
        if isinstance(widget, mod.Gtk.Container):
            for child in widget.get_children():
                self._labels(child, out)
        return out

    def test_money_meter_shows_what_is_left_instead_of_a_reset(self):
        texts = self._labels(self.win._meter_row(mod.openrouter_info(TOOLTIP)['meters'][0]))
        self.assertIn('$9.86 left', texts)
        self.assertNotIn('⟳ —', texts, 'a balance has no reset time to show')

    def test_time_meter_still_shows_the_reset(self):
        # the other vendors must keep the behaviour they always had
        meter = {'name': 'Session', 'pct': 25, 'trend': '', 'reset': '2h 47m'}
        self.assertIn('⟳ 2h 47m', self._labels(self.win._meter_row(meter)))

    def _hero(self, data):
        """Labels that join a name and a tail with ' · '.

        The footer (today · week · month) also contains ' · ', so this returns more than the hero
        line — the assertions below compare whole labels, which no other label can satisfy.
        """
        texts = self._labels(self.win.make_card('OpenRouter', data))
        return [t for t in texts if ' · ' in t]

    def test_hero_says_how_much_money_is_left(self):
        # proven missing by mutation: restoring the old "resets in {reset}" hero left the whole
        # suite green while the card read "Balance · resets in —"
        data = {'text': '$9.86', 'tooltip': '', 'class': 'low',
                'info': mod.openrouter_info(TOOLTIP)}
        self.assertIn('Balance · $9.86 left', self._hero(data))

    def test_hero_of_a_time_vendor_still_says_when_it_resets(self):
        info = {'plan': '', 'updated': '', 'extras': [],
                'meters': [{'name': 'Session', 'pct': 25, 'trend': '', 'reset': '2h 47m'}]}
        data = {'text': '25%', 'tooltip': '', 'class': 'mid', 'info': info}
        self.assertIn('Session · resets in 2h 47m', self._hero(data))

    def test_degraded_card_shows_no_key_on_screen(self):
        tooltip = 'OpenRouter — sk-or-v1-aec...212\nBalance\n$1..0 of $10.00 used (1%)\npaid tier'
        data = {'text': '$9.86', 'tooltip': tooltip, 'class': 'low',
                'info': mod.openrouter_blank(tooltip)}
        texts = self._labels(self.win.make_card('OpenRouter', data))
        self.assertIn('paid tier', texts)
        self.assertFalse(any('sk-or' in t for t in texts))

    def test_card_renders_the_money_card_without_the_key(self):
        data = {'text': '$9.86 · $0.14', 'tooltip': '', 'class': 'low',
                'info': mod.openrouter_info(TOOLTIP)}
        texts = self._labels(self.win.make_card('OpenRouter', data))
        self.assertIn('OpenRouter', texts)
        self.assertIn('paid tier', texts)
        self.assertIn('Balance', texts)
        self.assertIn('Per-key limit', texts)
        self.assertTrue(any('$9.86 left' in t for t in texts))
        self.assertFalse(any('sk-or' in t for t in texts), 'key fragment rendered on the card')


if __name__ == '__main__':
    unittest.main()
