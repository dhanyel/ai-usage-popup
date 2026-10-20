#!/usr/bin/env python3
"""Tests for the extra Claude cards — one per [[anthropic.accounts]] entry in ai-usagebar's config.

Run: python3 -m unittest test_accounts -v
"""
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
_loader = importlib.machinery.SourceFileLoader('aiusage_accounts', str(HERE / 'ai-usage-popup'))
_spec = importlib.util.spec_from_loader('aiusage_accounts', _loader)
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)


def write_config(text):
    fh = tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False)
    fh.write(text)
    fh.close()
    return Path(fh.name)


class TestVendorEntries(unittest.TestCase):
    def setUp(self):
        self._orig = mod.USAGEBAR_CONFIG

    def tearDown(self):
        mod.USAGEBAR_CONFIG = self._orig

    def test_no_anthropic_section_means_only_the_default_cards(self):
        mod.USAGEBAR_CONFIG = write_config('[zai]\napi_key = "x"\n')
        self.assertEqual(mod.vendor_entries(), mod.VENDORS)

    def test_missing_config_file_means_only_the_default_cards(self):
        mod.USAGEBAR_CONFIG = Path('/does/not/exist/config.toml')
        self.assertEqual(mod.vendor_entries(), mod.VENDORS)

    def test_broken_toml_means_only_the_default_cards(self):
        mod.USAGEBAR_CONFIG = write_config('not [ toml')
        self.assertEqual(mod.vendor_entries(), mod.VENDORS)

    def test_each_account_becomes_a_claude_card(self):
        mod.USAGEBAR_CONFIG = write_config(
            '[[anthropic.accounts]]\nlabel = "trab"\npath = "/tmp/a.json"\n'
            '[[anthropic.accounts]]\nlabel = "pessoal"\npath = "/tmp/b.json"\n')
        entries = mod.vendor_entries()
        self.assertEqual(entries[:len(mod.VENDORS)], mod.VENDORS)
        self.assertEqual(entries[len(mod.VENDORS):],
                         [('anthropic@trab', 'Claude · trab'),
                          ('anthropic@pessoal', 'Claude · pessoal')])

    def test_malformed_entries_are_skipped_not_fatal(self):
        mod.USAGEBAR_CONFIG = write_config(
            '[[anthropic.accounts]]\npath = "/tmp/no-label.json"\n'   # no label
            '[[anthropic.accounts]]\nlabel = 42\n'                    # not a string
            'anthropic_accounts = "wrong shape"\n')                   # wrong shape entirely
        self.assertEqual(mod.vendor_entries(), mod.VENDORS)


class TestRunVendorAccount(unittest.TestCase):
    def test_account_selects_the_named_account(self):
        payload = json.loads((HERE / 'fixtures' / 'anthropic.json').read_text())
        with mock.patch.object(mod.subprocess, 'check_output',
                               return_value=json.dumps(payload)) as out, \
             mock.patch.object(mod, 'AI', '/usr/bin/ai-usagebar'):
            result = mod.run_vendor('anthropic@trab')
        self.assertEqual(out.call_args[0][0],
                         ['/usr/bin/ai-usagebar', '--vendor', 'anthropic',
                          '--json', '--account', 'trab'])
        self.assertNotEqual(result['text'], 'unavailable')

    def test_plain_vendor_stays_without_account(self):
        payload = json.loads((HERE / 'fixtures' / 'anthropic.json').read_text())
        with mock.patch.object(mod.subprocess, 'check_output',
                               return_value=json.dumps(payload)) as out, \
             mock.patch.object(mod, 'AI', '/usr/bin/ai-usagebar'):
            mod.run_vendor('anthropic')
        self.assertEqual(out.call_args[0][0],
                         ['/usr/bin/ai-usagebar', '--vendor', 'anthropic', '--json'])


if __name__ == '__main__':
    unittest.main()
