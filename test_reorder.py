"""Card insertion and refresh behavior, using real GTK widgets under Xvfb."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from test_parsing import mod


@unittest.skipUnless(mod.Gtk.init_check()[0], 'GTK display required (use xvfb-run)')
class TestCardOrder(unittest.TestCase):
    def setUp(self):
        config = tempfile.TemporaryDirectory()
        self.addCleanup(config.cleanup)
        self.config = Path(config.name)
        environment = patch.dict(mod.os.environ, {'XDG_CONFIG_HOME': str(self.config)})
        environment.start()
        self.addCleanup(environment.stop)
        with patch.object(mod.UsageWindow, 'refresh'):
            self.window = mod.UsageWindow()
        self.addCleanup(self.window.destroy)
        self.results = [(v, label, {'text': '10%', 'class': 'low'})
                        for v, label in mod.VENDORS]
        self.window.render(self.results)

    def visible_order(self):
        grid = self.window.body.get_children()[0]
        return [grid.get_child_at(i % 2, i // 2).vendor_id
                for i in range(len(grid.get_children()))]

    def test_move_last_to_first_shifts_others_right_across_rows(self):
        self.window.move_card('kimi', 'anthropic')
        self.assertEqual(self.visible_order(),
                         ['kimi', 'anthropic', 'openai', 'zai', 'openrouter', 'deepseek',
                          'qwen'])

    def test_move_first_to_later_position_is_insertion_not_swap(self):
        self.window.move_card('anthropic', 'openrouter')
        self.assertEqual(self.visible_order(),
                         ['openai', 'zai', 'openrouter', 'anthropic', 'deepseek', 'kimi',
                          'qwen'])

    def test_refresh_keeps_order(self):
        self.window.move_card('zai', 'anthropic')
        self.window.render(self.results)
        self.assertEqual(self.visible_order(),
                         ['zai', 'anthropic', 'openai', 'openrouter', 'deepseek', 'kimi',
                          'qwen'])

    def test_drop_callback_moves_the_source_to_the_target_slot(self):
        grid = self.window.card_grid
        source = grid.get_child_at(1, 2)
        target = grid.get_child_at(0, 0)
        with patch.object(mod.Gtk, 'drag_get_source_widget', return_value=source), \
                patch.object(mod.Gtk, 'drag_finish'):
            self.window._drop_card(target, object(), 0, 0, 1)
        self.assertEqual(self.visible_order(),
                         ['kimi', 'anthropic', 'openai', 'zai', 'openrouter', 'deepseek',
                          'qwen'])

    def test_foreign_drop_does_not_change_order(self):
        target = self.window.card_grid.get_child_at(0, 0)
        with patch.object(mod.Gtk, 'drag_get_source_widget', return_value=None), \
                patch.object(mod.Gtk, 'drag_finish'):
            self.window._drop_card(target, object(), 0, 0, 1)
        self.assertEqual(self.visible_order(), [v for v, _ in mod.VENDORS])

    def test_offline_vendor_can_return_after_reordering(self):
        self.window.render([row for row in self.results if row[0] != 'openai'])
        self.window.move_card('kimi', 'anthropic')
        self.assertEqual(self.visible_order(),
                         ['kimi', 'anthropic', 'zai', 'openrouter', 'deepseek', 'qwen'])
        self.window.render(self.results)
        self.assertEqual(self.visible_order(),
                         ['kimi', 'openai', 'anthropic', 'zai', 'openrouter', 'deepseek',
                          'qwen'])

    def test_new_account_added_on_refresh_can_be_reordered(self):
        self.window.render(self.results + [('anthropic@work', 'Claude work',
                                           {'text': '10%', 'class': 'low'})])
        self.window.move_card('anthropic@work', 'anthropic')
        self.assertEqual(self.visible_order(),
                         ['anthropic@work', 'anthropic', 'openai', 'zai',
                          'openrouter', 'deepseek', 'kimi', 'qwen'])

    def reopen(self):
        self.window.destroy()
        with patch.object(mod.UsageWindow, 'refresh'):
            self.window = mod.UsageWindow()
        self.addCleanup(self.window.destroy)
        self.window.render(self.results)

    def test_order_survives_closing_and_reopening_with_extra_account(self):
        self.results.append(('anthropic@work', 'Claude work',
                             {'text': '10%', 'class': 'low'}))
        self.window.render(self.results)
        self.window.move_card('anthropic@work', 'anthropic')
        self.reopen()
        self.assertEqual(self.visible_order(),
                         ['anthropic@work', 'anthropic', 'openai', 'zai',
                          'openrouter', 'deepseek', 'kimi', 'qwen'])
        saved = self.config / 'ai-usage-popup' / 'card-order.json'
        self.assertEqual(json.loads(saved.read_text()), self.visible_order())

    def test_invalid_preferences_fall_back_to_default_order(self):
        saved = self.config / 'ai-usage-popup' / 'card-order.json'
        saved.parent.mkdir()
        for payload in ('broken json', '{}', '[1, null]', '["kimi", {}]'):
            with self.subTest(payload=payload):
                saved.write_text(payload)
                self.reopen()
                self.assertEqual(self.visible_order(), [v for v, _ in mod.VENDORS])

    def test_saved_duplicates_are_removed_and_new_vendors_are_appended(self):
        saved = self.config / 'ai-usage-popup' / 'card-order.json'
        saved.parent.mkdir()
        saved.write_text('["kimi", "kimi", "old-account", "openai"]')
        self.reopen()
        self.assertEqual(self.visible_order(),
                         ['kimi', 'openai', 'anthropic', 'zai', 'openrouter', 'deepseek',
                          'qwen'])

    def test_unwritable_config_does_not_prevent_reordering(self):
        (self.config / 'ai-usage-popup').write_text('not a directory')
        self.window.move_card('kimi', 'anthropic')
        self.assertEqual(self.visible_order(),
                         ['kimi', 'anthropic', 'openai', 'zai', 'openrouter', 'deepseek',
                          'qwen'])

    def test_same_or_unknown_card_does_not_change_order(self):
        self.window.move_card('openai', 'openai')
        self.window.move_card('missing', 'openai')
        self.assertEqual(self.visible_order(), [v for v, _ in mod.VENDORS])


if __name__ == '__main__':
    unittest.main()
