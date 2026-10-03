#!/usr/bin/env python3
"""Tests for reading ai-usagebar's tooltip into a card.

Run: python3 -m unittest

The fixtures in fixtures/ are real `ai-usagebar --vendor <name> --json` outputs:
Pango markup, a box-drawing frame, Nerd Font icons and block-character bars.
"""
import importlib.machinery
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).parent
_loader = importlib.machinery.SourceFileLoader('aiusage_parsing', str(HERE / 'ai-usage-popup'))
_spec = importlib.util.spec_from_loader('aiusage_parsing', _loader)
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)


def tooltip(vendor):
    return json.loads((HERE / 'fixtures' / f'{vendor}.json').read_text())['tooltip']


class TestStripMarkup(unittest.TestCase):
    def test_removes_markup_frame_and_icons_but_keeps_the_bars(self):
        text = mod.strip_markup(tooltip('anthropic'))
        self.assertNotIn('<span', text)
        for frame in '╭╮╰╯│':
            self.assertNotIn(frame, text)
        self.assertNotIn('\U000f051f', text)   # Nerd Font icon
        self.assertNotIn('⏱', text)
        self.assertIn('█░░░', text)            # bars stay: they mark a meter line
        self.assertEqual(text.splitlines()[0], 'Claude Team 5x')

    def test_drops_blank_lines_and_collapses_spaces(self):
        self.assertEqual(mod.strip_markup('<b>  a   b </b>\n\n   \nc'), 'a b\nc')


class TestParseTooltip(unittest.TestCase):
    def test_claude_meters_with_trend_and_reset(self):
        info = mod.parse_tooltip(tooltip('anthropic'), 'Claude')
        self.assertEqual(info['plan'], 'Team 5x')   # vendor name stripped from the title
        self.assertEqual(info['meters'], [
            {'name': 'Session', 'pct': 7, 'trend': '↓', 'reset': '2h 53m'},
            {'name': 'Weekly', 'pct': 4, 'trend': '↓', 'reset': '6d 9h'},
            {'name': 'Fable weekly', 'pct': 0, 'trend': '', 'reset': '6d 9h'},
        ])
        self.assertEqual(info['updated'], '10:26')
        self.assertEqual(info['extras'], [])

    def test_codex_keeps_a_title_without_the_vendor_name_and_collects_credits(self):
        info = mod.parse_tooltip(tooltip('openai'), 'Codex')
        self.assertEqual(info['plan'], 'ChatGPT Plus')
        self.assertEqual([(m['name'], m['pct'], m['reset']) for m in info['meters']],
                         [('Codex 5h', 0, '4h 59m'), ('Codex weekly', 2, '6d 7h')])
        self.assertEqual(info['extras'][0], 'Credits')
        self.assertIn('balance: 0', info['extras'])

    def test_a_bar_without_a_label_gets_a_numbered_name(self):
        info = mod.parse_tooltip('Vendor Pro\n████░░░░ 50%\nResets in 1h', 'Vendor')
        self.assertEqual(info['meters'], [{'name': 'Usage 1', 'pct': 50, 'trend': '', 'reset': '1h'}])

    def test_upward_trend(self):
        info = mod.parse_tooltip('X\nDaily\n██░░ 30% ↑', 'X')
        self.assertEqual(info['meters'][0]['trend'], '↑')

    def test_empty_tooltip(self):
        self.assertEqual(mod.parse_tooltip('', 'Claude'),
                         {'plan': '', 'meters': [], 'extras': [], 'updated': ''})


if __name__ == '__main__':
    unittest.main()
