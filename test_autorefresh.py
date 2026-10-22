"""Auto-refresh countdown: formatting and timer behavior, using real GTK widgets under Xvfb."""
import unittest
from unittest.mock import patch

from test_parsing import mod


class TestCountdownFormat(unittest.TestCase):
    def test_full_interval_shows_five_minutes(self):
        self.assertEqual(mod.fmt_countdown(300), 'next in 5:00')

    def test_mid_cycle_shows_minutes_and_padded_seconds(self):
        self.assertEqual(mod.fmt_countdown(252), 'next in 4:12')

    def test_under_a_minute_is_zero_padded(self):
        self.assertEqual(mod.fmt_countdown(59), 'next in 0:59')

    def test_fraction_rounds_up_so_the_window_opens_at_five(self):
        # ceil, not round: showing 4:59 for the whole first second would understate the wait,
        # and floor would leave 0:00 on screen while the refresh is already late.
        self.assertEqual(mod.fmt_countdown(299.2), 'next in 5:00')

    def test_zero_reads_zero(self):
        self.assertEqual(mod.fmt_countdown(0), 'next in 0:00')

    def test_an_hour_reads_as_sixty_minutes_not_a_fake_hour(self):
        self.assertEqual(mod.fmt_countdown(3600), 'next in 60:00')


@unittest.skipUnless(mod.Gtk.init_check()[0], 'GTK display required (use xvfb-run)')
class TestAutoRefreshTimer(unittest.TestCase):
    def setUp(self):
        # The patcher outlives setUp on purpose: closing it there left the assertions calling the
        # real refresh(), which not only has no assert_not_called — it would collect from all seven
        # vendors for real.
        patcher = patch.object(mod.UsageWindow, 'refresh')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = mod.UsageWindow()
        self.addCleanup(self.window.destroy)
        # __init__ ends with self.refresh(); that call belongs to the constructor, not to the test.
        self.window.refresh.reset_mock()
        self.results = [(v, label, {'text': '10%', 'class': 'low'})
                        for v, label in mod.VENDORS]

    def test_default_interval_is_five_minutes(self):
        self.assertEqual(mod.AUTO_REFRESH_SECONDS, 300)
        self.assertEqual(self.window.auto_refresh, 300)

    def test_render_arms_the_next_refresh_a_full_interval_ahead(self):
        before = mod.time.monotonic()
        self.window.render(self.results)
        after = mod.time.monotonic()
        # Armed on completion, not on request: a slow cycle (Z.AI 15s, Qwen 30s) must not eat
        # its own interval.
        self.assertGreaterEqual(self.window._next_refresh, before + self.window.auto_refresh)
        self.assertLessEqual(self.window._next_refresh, after + self.window.auto_refresh)

    def test_render_clears_the_in_flight_flag(self):
        self.window._refreshing = True
        self.window.render(self.results)
        self.assertFalse(self.window._refreshing)

    def test_render_paints_the_countdown_beside_the_stamp(self):
        self.window.render(self.results)
        self.assertIn('next in 5:00', self.window.subtitle.get_text())
        self.assertTrue(self.window._subtitle_base)

    def test_expired_tick_triggers_a_refresh(self):
        self.window.render(self.results)
        self.window._next_refresh = mod.time.monotonic() - 1
        self.window._tick()
        self.window.refresh.assert_called_once_with()

    def test_tick_while_refreshing_neither_fires_nor_repaints(self):
        self.window.render(self.results)
        self.window._refreshing = True
        self.window.subtitle.set_text('updating…')
        self.window._next_refresh = mod.time.monotonic() - 1
        self.assertTrue(self.window._tick())
        self.window.refresh.assert_not_called()
        self.assertEqual(self.window.subtitle.get_text(), 'updating…')

    def test_tick_with_time_left_paints_the_countdown(self):
        self.window.render(self.results)
        self.window._next_refresh = mod.time.monotonic() + 252
        self.window._tick()
        self.assertEqual(self.window.subtitle.get_text(),
                         self.window._subtitle_base + ' · next in 4:12')
        self.window.refresh.assert_not_called()

    def test_tick_keeps_the_timer_alive(self):
        self.window.render(self.results)
        self.assertTrue(self.window._tick())

    def test_tick_before_the_first_render_leaves_the_label_alone(self):
        self.window.subtitle.set_text('loading…')
        self.assertTrue(self.window._tick())
        self.assertEqual(self.window.subtitle.get_text(), 'loading…')
        self.window.refresh.assert_not_called()

    def test_manual_refresh_rearms_instead_of_stacking(self):
        self.window.render(self.results)
        first = self.window._next_refresh
        self.window._next_refresh = mod.time.monotonic() + 10
        self.window.render(self.results)
        # A second render (what ↻ Refresh ends in) pushes the deadline out again, so the manual
        # read is never followed one second later by an automatic one.
        self.assertGreater(self.window._next_refresh, mod.time.monotonic() + 10)
        self.assertGreaterEqual(self.window._next_refresh, first)


@unittest.skipUnless(mod.Gtk.init_check()[0], 'GTK display required (use xvfb-run)')
class TestRealRefreshCycle(unittest.TestCase):
    """The real `refresh()` — only the collection is replaced.

    TestAutoRefreshTimer mocks `refresh` itself, which is exactly the method the timer fires, so
    nothing there proves the cycle sets and clears the in-flight flag or re-arms on completion.
    """

    def setUp(self):
        # Constructed under a patch so __init__'s own refresh() collects nothing; the patch is
        # closed on purpose here — this class wants the real method back.
        with patch.object(mod.UsageWindow, 'refresh'):
            self.window = mod.UsageWindow()
        self.addCleanup(self.window.destroy)

    def collect(self):
        """Run one real cycle, then deliver the results the way the main loop would."""
        handed = []
        with patch.object(mod.GLib, 'idle_add', lambda fn, *a: handed.append((fn, a))):
            with patch.object(mod, 'vendor_entries', return_value=[('anthropic', 'Claude')]), \
                    patch.object(mod, 'run_vendor',
                                 return_value={'text': '10%', 'class': 'low'}):
                self.window.refresh()
                self.assertTrue(self.window._refreshing)
                self.assertFalse(self.window.refresh_btn.get_sensitive())
                deadline = mod.time.monotonic() + 5
                while not handed and mod.time.monotonic() < deadline:
                    mod.time.sleep(0.01)
        self.assertTrue(handed, 'the worker thread never handed results to the main loop')
        fn, args = handed[0]
        fn(*args)   # render, on this thread — GTK calls from the worker are not ours to make

    def test_a_real_cycle_clears_the_in_flight_flag_and_rearms(self):
        self.collect()
        self.assertFalse(self.window._refreshing)
        self.assertTrue(self.window.refresh_btn.get_sensitive())
        self.assertGreater(self.window._next_refresh,
                           mod.time.monotonic() + self.window.auto_refresh - 5)

    def test_a_real_cycle_paints_the_countdown_beside_the_stamp(self):
        self.collect()
        text = self.window.subtitle.get_text()
        self.assertIn('1 vendors', text)
        self.assertIn('next in 5:00', text)

    def test_a_second_cycle_pushes_the_deadline_out_again(self):
        self.collect()
        first = self.window._next_refresh
        self.window._next_refresh = mod.time.monotonic() + 1   # about to expire
        self.collect()
        # This is what stops a manual ↻ Refresh from being followed one second later by an
        # automatic one: every completed cycle re-arms a full interval ahead.
        self.assertGreater(self.window._next_refresh, first)


if __name__ == '__main__':
    unittest.main()
