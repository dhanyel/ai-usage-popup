"""Strip mode: meter helpers and mode persistence (pure, no GTK)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_parsing import mod


def meter(name, pct=None, reset='', note=''):
    m = {'name': name, 'trend': ''}
    if pct is not None:
        m['pct'] = pct
    m['reset'] = reset
    if note:
        m['note'] = note
    return m


class TestPickStripMeters(unittest.TestCase):
    def pick(self, meters):
        return mod.pick_strip_meters({'meters': meters})

    def test_claude_weekly_is_weekly_never_fable(self):
        window, weekly = self.pick([meter('Session'), meter('Weekly'), meter('Fable weekly')])
        self.assertEqual((window['name'], weekly['name']), ('Session', 'Weekly'))

    def test_session_plus_fable_only_has_no_weekly(self):
        window, weekly = self.pick([meter('Session'), meter('Fable weekly')])
        self.assertEqual(window['name'], 'Session')
        self.assertIsNone(weekly)

    def test_qwen_monthly_only_has_no_weekly(self):
        window, weekly = self.pick([meter('Monthly', 29.0, '30d 3h')])
        self.assertEqual(window['name'], 'Monthly')
        self.assertIsNone(weekly)

    def test_openrouter_pair_in_documented_order(self):
        window, weekly = self.pick([meter('Balance'), meter('Per-key limit')])
        self.assertEqual((window['name'], weekly['name']), ('Balance', 'Per-key limit'))

    def test_openrouter_pair_reversed_by_the_pct_sort(self):
        # the parser sorts by pct desc, so Per-key limit can legitimately come first
        window, weekly = self.pick([meter('Per-key limit'), meter('Balance')])
        self.assertEqual((window['name'], weekly['name']), ('Per-key limit', 'Balance'))

    def test_openrouter_with_a_single_meter_does_not_index_past_the_end(self):
        window, weekly = self.pick([meter('Balance')])
        self.assertEqual(window['name'], 'Balance')
        self.assertIsNone(weekly)

    def test_non_weekly_second_meter_is_not_promoted_to_weekly(self):
        window, weekly = self.pick([meter('Session'), meter('Credits')])
        self.assertEqual(window['name'], 'Session')
        self.assertIsNone(weekly)

    def test_no_info_yields_two_absent_meters(self):
        self.assertEqual(mod.pick_strip_meters(None), (None, None))

    def test_empty_meters_yields_two_absent_meters(self):
        self.assertEqual(mod.pick_strip_meters({'meters': []}), (None, None))


class TestFmtMeterLine(unittest.TestCase):
    def test_openrouter_money_reads_note_not_the_empty_reset(self):
        line = mod.fmt_meter_line(meter('Balance', 73.0, reset='', note='$13.61 left'))
        self.assertEqual(line, 'Balance · 73% · $13.61 left')

    def test_time_meter_reads_reset_when_there_is_no_note(self):
        line = mod.fmt_meter_line(meter('Weekly', 92.0, reset='1d 10h'))
        self.assertEqual(line, 'Weekly · 92% · 1d 10h')

    def test_dash_reset_is_dropped(self):
        self.assertEqual(mod.fmt_meter_line(meter('Monthly', 29.0, reset='—')), 'Monthly · 29%')

    def test_name_only_when_there_is_no_figure(self):
        self.assertEqual(mod.fmt_meter_line(meter('Session')), 'Session')


class TestModePersistence(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(mod.os.environ, {'XDG_CONFIG_HOME': tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.config = Path(tmp.name)

    def saved(self):
        return self.config / 'ai-usage-popup' / 'mode.json'

    def test_default_is_cards_when_there_is_no_file(self):
        self.assertEqual(mod.load_mode(), 'cards')

    def test_toolbar_roundtrips(self):
        mod.save_mode('toolbar')
        self.assertEqual(mod.load_mode(), 'toolbar')
        self.assertEqual(json.loads(self.saved().read_text()), {'mode': 'toolbar'})

    def test_legacy_strip_is_read_as_toolbar(self):
        self.saved().parent.mkdir(parents=True, exist_ok=True)
        self.saved().write_text('{"mode": "strip"}')
        self.assertEqual(mod.load_mode(), 'toolbar')

    def test_invalid_payloads_fall_back_to_cards(self):
        self.saved().parent.mkdir(parents=True, exist_ok=True)
        for payload in ('broken json', '{}', '{"mode": 1}', '{"mode": "banana"}'):
            with self.subTest(payload=payload):
                self.saved().write_text(payload)
                self.assertEqual(mod.load_mode(), 'cards')

    def test_unwritable_config_does_not_raise(self):
        (self.config / 'ai-usage-popup').write_text('not a directory')
        mod.save_mode('toolbar')   # must not throw
        self.assertEqual(mod.load_mode(), 'cards')


class TestBottomStrut(unittest.TestCase):
    """_NET_WM_STRUT_PARTIAL values for the strip the toolbar reserves (pure, no GTK)."""

    def test_reserves_the_bar_height_above_the_bottom_edge(self):
        # 1080p root, bar flush with the bottom edge, 64px tall, from x=72 across 1238px
        self.assertEqual(mod.bottom_strut(1080, 72, 1238, 1080, 64),
                         [0, 0, 0, 64, 0, 0, 0, 0, 0, 0, 72, 1309])

    def test_bottom_counts_from_the_root_window_not_the_monitor(self):
        # a monitor whose bottom edge sits 64px above the root's: the strut must grow to match
        self.assertEqual(mod.bottom_strut(1080, 0, 800, 1016, 64)[3], 128)

    def test_only_the_bottom_field_and_the_x_range_are_set(self):
        strut = mod.bottom_strut(1080, 72, 1238, 1080, 64)
        self.assertEqual(strut[:3], [0, 0, 0])
        self.assertEqual(strut[4:10], [0] * 6)


@unittest.skipUnless(mod.Gtk.init_check()[0], 'GTK display required (use xvfb-run)')
class TestStripWindow(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(mod.os.environ, {'XDG_CONFIG_HOME': tmp.name})
        env.start()
        self.addCleanup(env.stop)
        patcher = patch.object(mod.UsageWindow, 'refresh')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = mod.UsageWindow()
        self.addCleanup(self.window.destroy)
        self.window.refresh.reset_mock()
        self.window.mode = 'cards'

        def m(name, pct=None, reset='', note=''):
            return meter(name, pct, reset, note)

        self.results = [
            ('anthropic', 'Claude', {'text': '3%', 'class': 'low',
                                     'info': {'plan': '', 'updated': '', 'extras': [],
                                              'meters': [m('Session', 3.0, '1h 38m'),
                                                         m('Weekly', 92.0, '1d 10h'),
                                                         m('Fable weekly', 0.0, '1d 10h')]}}),
            ('openrouter', 'OpenRouter', {'text': '73%', 'class': 'mid',
                                          'info': {'plan': '', 'updated': '', 'extras': [],
                                                   'meters': [m('Balance', 73.0, note='$13.61 left'),
                                                              m('Per-key limit', 73.0, note='$13.61 left')]}}),
            ('deepseek', 'DeepSeek', {'text': 'unavailable', 'tooltip': 'no api key',
                                      'class': 'critical'}),
        ]

    def strip_blocks(self):
        bar = self.window.body.get_children()[0]
        return [c for c in bar.get_children() if c.get_style_context().has_class('block')]

    def block_name(self, block):
        return block.get_children()[0].get_children()[0].get_text()

    def block_lines(self, block):
        return [row.get_children()[1].get_text() for row in block.get_children()[1:]]

    def line_dot_classes(self, row):
        return [c for c in ('low', 'mid', 'high', 'critical', 'unknown')
                if row.get_children()[0].get_style_context().has_class(c)]

    def test_strip_builds_one_block_per_configured_vendor_only(self):
        self.window.mode = 'toolbar'
        self.window._rebuild(self.results)
        blocks = self.strip_blocks()
        self.assertEqual([self.block_name(b) for b in blocks], ['Claude', 'OpenRouter'])

    def test_claude_block_shows_session_and_weekly_but_not_fable(self):
        self.window.mode = 'toolbar'
        self.window._rebuild(self.results)
        claude = self.strip_blocks()[0]
        self.assertEqual(self.block_lines(claude),
                         ['Session · 3% · 1h 38m', 'Weekly · 92% · 1d 10h'])

    def test_openrouter_block_shows_the_money_pair(self):
        self.window.mode = 'toolbar'
        self.window._rebuild(self.results)
        orouter = self.strip_blocks()[1]
        self.assertEqual(self.block_lines(orouter),
                         ['Balance · 73% · $13.61 left', 'Per-key limit · 73% · $13.61 left'])

    def test_each_meter_line_carries_its_own_status_dot(self):
        # Each meter has its own usage, so the color lives on the line, not on the vendor name:
        # a calm 3% session sits next to a 92% weekly in the same block.
        self.window.mode = 'toolbar'
        self.window._rebuild(self.results)
        session, weekly = self.strip_blocks()[0].get_children()[1:]
        self.assertEqual(self.line_dot_classes(session), ['low'])
        self.assertEqual(self.line_dot_classes(weekly), ['critical'])

    def test_meter_without_a_figure_gets_the_unknown_dot(self):
        self.window.mode = 'toolbar'
        self.window._rebuild([('anthropic', 'Claude',
                               {'text': '3%', 'class': 'low',
                                'info': {'plan': '', 'updated': '', 'extras': [],
                                         'meters': [meter('Session')]}})])
        row = self.strip_blocks()[0].get_children()[1]
        self.assertEqual(self.line_dot_classes(row), ['unknown'])

    def test_vendor_name_row_carries_no_dot(self):
        self.window.mode = 'toolbar'
        self.window._rebuild(self.results)
        top = self.strip_blocks()[0].get_children()[0]
        self.assertFalse(any(c.get_style_context().has_class('dot') for c in top.get_children()))

    def test_vendor_without_info_falls_back_to_parse_tooltip(self):
        info = {'meters': [meter('Session', 3.0, '1h'), meter('Weekly', 92.0, '1d')]}
        with patch.object(mod, 'parse_tooltip', return_value=info) as pt:
            self.window.mode = 'toolbar'
            self.window._rebuild([('anthropic', 'Claude',
                                   {'text': '3%', 'class': 'low', 'info': None, 'tooltip': 'x'})])
            self.assertEqual(self.block_lines(self.strip_blocks()[0]),
                             ['Session · 3% · 1h', 'Weekly · 92% · 1d'])
        pt.assert_called_once()

    def test_degraded_openrouter_renders_a_name_only_block_without_raising(self):
        self.window.mode = 'toolbar'
        self.window._rebuild([('openrouter', 'OpenRouter',
                               {'text': '—', 'class': 'unknown', 'tooltip': 'OpenRouter — sk-or',
                                'info': {'plan': '', 'meters': [], 'extras': [], 'updated': ''}})])
        blocks = self.strip_blocks()
        self.assertEqual([self.block_name(b) for b in blocks], ['OpenRouter'])
        self.assertEqual(self.block_lines(blocks[0]), [])

    def test_toggle_preserves_the_armed_refresh_and_does_not_recollect(self):
        self.window.render(self.results)
        armed = self.window._next_refresh
        self.window._toggle_mode()
        self.assertEqual(self.window.mode, 'toolbar')
        self.assertEqual(self.window._next_refresh, armed)
        self.window.refresh.assert_not_called()

    def test_toggle_during_a_collection_keeps_the_in_flight_state(self):
        self.window._refreshing = True
        self.window.refresh_btn.set_sensitive(False)
        self.window._toggle_mode()
        self.assertTrue(self.window._refreshing)
        self.assertFalse(self.window.refresh_btn.get_sensitive())
        self.window.refresh.assert_not_called()

    def test_toggle_before_the_first_render_does_not_crash(self):
        self.assertIsNone(self.window._last_results)
        self.window._toggle_mode()
        self.assertEqual(self.window.mode, 'toolbar')
        self.window.refresh.assert_not_called()

    def test_toggle_after_a_collection_reclassifies_through_the_same_rebuild(self):
        self.window.render(self.results)          # cards
        self.window._toggle_mode()                 # -> toolbar
        self.assertEqual([self.block_name(b) for b in self.strip_blocks()],
                         ['Claude', 'OpenRouter'])

    def test_cards_strip_cards_restores_the_cards_layout(self):
        self.window.render(self.results)
        self.assertEqual(self.window.body.get_border_width(), 18)
        self.window._toggle_mode()
        self.assertNotEqual(self.window.body.get_border_width(), 18)
        self.window._toggle_mode()
        self.assertEqual(self.window.body.get_border_width(), 18)

    def test_opening_directly_in_strip_keeps_the_persisted_card_order(self):
        self.window.card_order = ['openrouter', 'anthropic', 'deepseek']
        self.window.mode = 'toolbar'
        self.window.render(self.results)
        self.assertEqual([self.block_name(b) for b in self.strip_blocks()],
                         ['OpenRouter', 'Claude'])


@unittest.skipUnless(mod.Gtk.init_check()[0], 'GTK display required (use xvfb-run)')
class TestStripHeader(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(mod.os.environ, {'XDG_CONFIG_HOME': tmp.name})
        env.start()
        self.addCleanup(env.stop)
        patcher = patch.object(mod.UsageWindow, 'refresh')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = mod.UsageWindow()
        self.addCleanup(self.window.destroy)
        self.window.refresh.reset_mock()

    def toolbar_bar(self):
        return self.window.body.get_children()[0]

    def test_toolbar_is_undecorated_and_puts_the_controls_in_the_body(self):
        # An undecorated window has no HeaderBar, so the i button and the one-line header must live
        # in the body bar — this is the regression the first toolbar capture exposed. _rebuild ends
        # with body.show_all(), so the controls must actually be visible, not just present.
        self.window.mode = 'toolbar'
        self.window._apply_presentation()
        self.window._rebuild([])
        self.assertFalse(self.window.get_decorated())
        bar = self.toolbar_bar()
        self.assertIn(self.window.cards_btn, bar.get_children())
        self.assertIn(self.window.oneline_label, bar.get_children())
        self.assertTrue(self.window.cards_btn.get_visible())
        self.assertTrue(self.window.oneline_label.get_visible())

    def test_cards_is_decorated_with_the_stacked_header(self):
        self.window.mode = 'cards'
        self.window._apply_presentation()
        self.window._rebuild([])
        self.assertTrue(self.window.get_decorated())
        # The stacked title lives in the HeaderBar (the titlebar), which only exists when decorated.
        self.assertIsInstance(self.window.get_titlebar(), mod.Gtk.HeaderBar)
        self.assertIsNotNone(self.window.titles.get_parent())
        self.assertIsInstance(self.toolbar_bar(), mod.Gtk.Grid)

    def test_alternating_flips_the_decoration(self):
        self.window.mode = 'cards'
        self.window._apply_presentation()
        self.assertTrue(self.window.get_decorated())
        self.window._toggle_mode()
        self.assertFalse(self.window.get_decorated())
        self.window._toggle_mode()
        self.assertTrue(self.window.get_decorated())

    def test_set_subtitle_mirrors_into_the_single_line(self):
        self.window._set_subtitle('updating…')
        self.assertEqual(self.window.subtitle.get_text(), 'updating…')
        self.assertEqual(self.window.oneline_label.get_text(), 'AI Usage · updating…')

    def test_entering_toolbar_mid_collection_shows_updating(self):
        self.window._set_subtitle('updating…')
        self.window._refreshing = True
        self.window._toggle_mode()   # cards -> toolbar while a collection is in flight
        self.assertEqual(self.window.oneline_label.get_text(), 'AI Usage · updating…')

    def test_single_line_tracks_the_countdown(self):
        self.window.mode = 'toolbar'
        self.window._update_mode_button()
        self.window._subtitle_base = 'updated at 10:49 · 8 vendors'
        self.window._paint_countdown(146)   # 2:26
        self.assertEqual(self.window.oneline_label.get_text(),
                         'AI Usage · updated at 10:49 · 8 vendors · next in 2:26')

    def test_clicking_the_i_button_opens_cards_without_typeerror(self):
        self.window.mode = 'toolbar'
        self.window._update_mode_button()
        self.window.cards_btn.emit('clicked')
        self.assertEqual(self.window.mode, 'cards')

    def test_toolbar_uses_the_dock_type_hint_so_the_wm_does_not_maximize_it(self):
        # Regression for the GNOME/mutter bug: a plain borderless window as wide as the screen gets
        # maximized; the DOCK hint makes the WM treat it as a panel instead.
        self.window.mode = 'toolbar'
        self.window._apply_presentation()
        self.assertEqual(self.window.get_type_hint(), mod.Gdk.WindowTypeHint.DOCK)

    def test_cards_uses_the_normal_type_hint(self):
        self.window.mode = 'cards'
        self.window._apply_presentation()
        self.assertEqual(self.window.get_type_hint(), mod.Gdk.WindowTypeHint.NORMAL)

    def test_toggle_remaps_the_window_so_the_compositor_sees_a_fresh_start(self):
        # The DOCK hint, the undecorated frame and the edge placement are only honoured when the
        # window is MAPPED with them, so a toggle deliberately unmaps and unrealizes: every switch
        # must present a brand-new GdkWindow built for the target mode.
        self.window.show_all()
        with patch.object(self.window, 'hide') as hide, \
                patch.object(self.window, 'unrealize') as unrealize:
            self.window._toggle_mode()
        hide.assert_called_once()
        unrealize.assert_called_once()
        self.assertTrue(self.window.get_visible())

    def test_controls_survive_repeated_mode_switches(self):
        # Regression for the GNOME bug: dropping the old bar destroyed the widgets still parented
        # in it, and a destroyed button loses its 'clicked' handler — after one round trip the
        # button did nothing. They must be detached BEFORE the bar is replaced.
        self.window.render([('anthropic', 'Claude',
                             {'text': '3%', 'class': 'low',
                              'info': {'plan': '', 'updated': '', 'extras': [],
                                       'meters': [meter('Session', 3.0, '1h 38m')]}})])   # cards
        self.window._toggle_mode()         # -> toolbar
        self.window._toggle_mode()         # -> cards
        self.window._toggle_mode()         # -> toolbar again
        self.assertEqual(self.window.mode, 'toolbar')
        bar = self.toolbar_bar()
        self.assertIn(self.window.cards_btn, bar.get_children())
        self.assertIn(self.window.oneline_label, bar.get_children())
        self.window.cards_btn.emit('clicked')   # the handler must still be alive
        self.assertEqual(self.window.mode, 'cards')


if __name__ == '__main__':
    unittest.main()
