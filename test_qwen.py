#!/usr/bin/env python3
"""Tests for the Qwen card — Bailian Token Plan usage, read through the `bl` CLI.

Run: python3 -m unittest test_qwen -v

`bl usage token-plan --output json` nests its numbers under `data`; both shapes are covered.
"""
import importlib.machinery
import importlib.util
import json
import unittest
from unittest import mock

_loader = importlib.machinery.SourceFileLoader('aiusage_qwen', 'ai-usage-popup')
_spec = importlib.util.spec_from_loader('aiusage_qwen', _loader)
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)

RESET = 1796000000000   # epoch ms, far enough ahead for a "Xd Yh" delta


def payload(nested=True):
    # the real API speaks fractions (0.0124 = 1.25% used, confirmed 2026-10-20)
    data = {'per1MonthPercentage': 0.0124, 'per1MonthResetTime': RESET}
    return json.dumps({'data': data} if nested else data)


class TestRunQwen(unittest.TestCase):
    def test_reads_the_monthly_gauge_from_the_nested_shape(self):
        with mock.patch.object(mod.subprocess, 'check_output', return_value=payload(True)):
            result = mod.run_qwen()
        self.assertEqual(result['text'], '1.2%')   # fraction scaled to percent, then rounded
        self.assertEqual(result['info']['plan'], 'Token Plan')
        meter = result['info']['meters'][0]
        self.assertEqual((meter['name'], meter['pct']), ('Monthly', 1.24))
        self.assertNotEqual(meter['reset'], '—')

    def test_reads_the_flat_shape_too(self):
        with mock.patch.object(mod.subprocess, 'check_output', return_value=payload(False)):
            self.assertEqual(mod.run_qwen()['info']['meters'][0]['pct'], 1.24)

    def test_percent_scale_stays_untouched(self):
        data = {'per1MonthPercentage': 42.0, 'per1MonthResetTime': RESET}
        with mock.patch.object(mod.subprocess, 'check_output',
                               return_value=json.dumps({'data': data})):
            self.assertEqual(mod.run_qwen()['info']['meters'][0]['pct'], 42.0)

    def test_missing_usage_says_the_login_fix_not_a_fake_number(self):
        with mock.patch.object(mod.subprocess, 'check_output',
                               return_value=json.dumps({'data': {}})):
            result = mod.run_qwen()
        self.assertEqual(result['text'], 'unavailable')
        self.assertEqual(result['fix'], 'bl auth login --console')

    def test_expired_console_session_reports_bls_own_reason(self):
        # bl exits 0 on this one, so the reason only survives if it is read out of the body.
        body = {'error': {'code': 3,
                          'message': 'Console session is not logged in or has expired.',
                          'hint': 'Run `bl auth login --console` to sign in.'}}
        with mock.patch.object(mod.subprocess, 'check_output', return_value=json.dumps(body)):
            result = mod.run_qwen()
        self.assertEqual(result['text'], 'unavailable')
        self.assertEqual(result['reason'], 'Console session is not logged in or has expired.')
        self.assertEqual(result['fix'], 'bl auth login --console')

    def test_error_body_without_message_falls_back_to_the_hint(self):
        body = {'error': {'code': 1, 'hint': 'Run `bl auth login --console`.'}}
        with mock.patch.object(mod.subprocess, 'check_output', return_value=json.dumps(body)):
            self.assertEqual(mod.run_qwen()['reason'], 'Run `bl auth login --console`.')

    def test_error_body_without_message_or_hint_still_degrades_loudly(self):
        with mock.patch.object(mod.subprocess, 'check_output',
                               return_value=json.dumps({'error': {'code': 1}})):
            result = mod.run_qwen()
        self.assertEqual(result['text'], 'unavailable')
        self.assertNotIn('info', result)

    def test_non_dict_error_body_does_not_hide_a_real_reading(self):
        data = {'error': 'ignored', 'per1MonthPercentage': 0.5, 'per1MonthResetTime': RESET}
        with mock.patch.object(mod.subprocess, 'check_output', return_value=json.dumps(data)):
            self.assertEqual(mod.run_qwen()['info']['meters'][0]['pct'], 50.0)

    def test_bl_failure_names_the_login(self):
        import subprocess as sp
        with mock.patch.object(mod.subprocess, 'check_output',
                               side_effect=sp.CalledProcessError(3, 'bl')):
            result = mod.run_qwen()
        self.assertIn('bl auth login --console', result['fix'])

    def test_non_json_output_degrades_loudly(self):
        with mock.patch.object(mod.subprocess, 'check_output', return_value='not json'):
            result = mod.run_qwen()
        self.assertEqual(result['text'], 'unavailable')
        self.assertNotIn('info', result)

    def test_timeout_degrades_loudly(self):
        import subprocess as sp
        with mock.patch.object(mod.subprocess, 'check_output',
                               side_effect=sp.TimeoutExpired('bl', 30)):
            self.assertEqual(mod.run_qwen()['text'], 'unavailable')

    def test_qwen_env_puts_nvm_bins_first(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            nvm_bin = mod.Path(tmp) / '.nvm/versions/node/v24/bin'
            nvm_bin.mkdir(parents=True)
            with mock.patch.object(mod.Path, 'home', classmethod(lambda cls: mod.Path(tmp))):
                env = mod.qwen_env()
        self.assertTrue(env['PATH'].startswith(str(nvm_bin) + ':'))

    def test_routing_sends_qwen_to_run_qwen(self):
        with mock.patch.object(mod, 'run_qwen', return_value={'text': 'x'}):
            self.assertEqual(mod.run_vendor('qwen'), {'text': 'x'})


if __name__ == '__main__':
    unittest.main()
