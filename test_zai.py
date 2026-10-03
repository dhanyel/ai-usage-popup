#!/usr/bin/env python3
"""Testes da leitura do Z.AI direto da API.

Rodar: python3 -m unittest

O script principal não tem extensão .py, então é carregado por SourceFileLoader.
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

# Resposta real da conta, capturada em 04/09/2026. `usage` é o limite; `currentValue`, o usado.
RESPOSTA_REAL = {
    "code": 200, "msg": "Operation successful", "success": True,
    "data": {
        "level": "lite",
        "limits": [
            # semanal vem PRIMEIRO de propósito: o código tem de ordenar por nextResetTime
            {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 10000,
             "currentValue": 44, "remaining": 9955, "percentage": 1,
             "nextResetTime": 1789152613998},
            {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000,
             "currentValue": 44, "remaining": 1955, "percentage": 2,
             "nextResetTime": 1788565955192},
        ],
    },
}


class FakeResposta:
    """Substituto de urlopen() — context manager com .read(), como o de verdade."""

    def __init__(self, corpo):
        self._corpo = corpo

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._corpo


def fake_urlopen(corpo, capturado):
    """Devolve um urlopen falso que registra em `capturado` como foi chamado."""
    def _fake(req, timeout=None):
        capturado['url'] = req.full_url
        capturado['metodo'] = req.get_method()
        capturado['headers'] = dict(req.headers)
        capturado['timeout'] = timeout
        return FakeResposta(corpo)
    return _fake


class TestTraducao(unittest.TestCase):
    """zai_info() é função pura: é aqui que um número errado passaria despercebido."""

    def setUp(self):
        self.info = mod.zai_info(RESPOSTA_REAL)

    def test_janela_curta_vem_primeiro(self):
        # a curta vira o número-herói e o badge do card
        self.assertEqual([m['name'] for m in self.info['meters']], ['Sessão 5h', 'Semanal'])

    def test_ordem_e_por_duracao_e_nao_por_horario_de_reset(self):
        """Os dois critérios coincidem no dia a dia e divergem no pior momento.

        Nas horas que antecedem o reset semanal, a semanal reseta ANTES da janela de 5h. Ordenar
        por reset poria a semanal (0,4%) como herói e esconderia a de 5h em 90% — justamente a que
        está estrangulando o uso.
        """
        payload = json.loads(json.dumps(RESPOSTA_REAL))
        semanal, curta = payload['data']['limits']
        semanal['nextResetTime'] = 1_700_000_000_000   # reseta JÁ
        curta['nextResetTime'] = 1_800_000_000_000     # reseta bem depois
        curta['currentValue'] = 1800                   # e é a que está quase estourando

        meters = mod.zai_info(payload)['meters']
        self.assertEqual(meters[0]['name'], 'Sessão 5h')
        self.assertAlmostEqual(meters[0]['pct'], 90.0)
        self.assertEqual(mod.klass_of(meters[0]['pct']), 'critical')

    def test_medidor_carrega_o_reset_formatado(self):
        # sem isto o card poderia exibir "reseta em 1788565955192" com os testes verdes
        for medidor in self.info['meters']:
            self.assertRegex(medidor['reset'], r'^(\d+[dhm]( \d+[hm])?|agora|—)$')

    def test_percentual_vem_do_usado_sobre_o_limite(self):
        curta, semanal = self.info['meters']
        self.assertAlmostEqual(curta['pct'], 44 / 2000 * 100)     # 2,2%
        self.assertAlmostEqual(semanal['pct'], 44 / 10000 * 100)  # 0,44%

    def test_nao_usa_o_percentual_arredondado_da_api(self):
        # a API devolve percentage=1 para 0,44% — arredonda para cima e apaga a diferença
        semanal = self.info['meters'][1]
        self.assertNotEqual(round(semanal['pct']), 1)
        self.assertEqual(mod.fmt_pct(semanal['pct']), '0,4')

    def test_plano_vem_do_level(self):
        self.assertEqual(self.info['plan'], 'GLM Coding Lite')

    def test_creditos_no_rodape(self):
        self.assertEqual(self.info['extras'],
                         ['créditos 44/2000 (sessão 5h) · 44/10000 (semanal)'])

    def test_unidade_desconhecida_degrada_mas_aparece(self):
        payload = json.loads(json.dumps(RESPOSTA_REAL))
        payload['data']['limits'][0]['unit'] = 99
        nomes = [m['name'] for m in mod.zai_info(payload)['meters']]
        self.assertIn('Janela 1·u99', nomes)   # aparece com rótulo degradado
        self.assertEqual(len(nomes), 2)        # e não some do card

    def test_semana_no_plural_quando_number_nao_e_um(self):
        payload = json.loads(json.dumps(RESPOSTA_REAL))
        payload['data']['limits'][0].update({'number': 2, 'usage': 20000})
        nomes = [m['name'] for m in mod.zai_info(payload)['meters']]
        self.assertIn('2 semanas', nomes)      # e não "Semanal", que mentiria o período
        self.assertNotIn('Semanal', nomes)

    def test_success_false_vira_erro(self):
        with self.assertRaises(ValueError):
            mod.zai_info({'success': False, 'msg': 'Authentication Failed'})

    def test_resposta_sem_janelas_vira_erro(self):
        with self.assertRaises(ValueError):
            mod.zai_info({'success': True, 'data': {'level': 'lite', 'limits': []}})

    def test_campo_de_uso_ausente_vira_erro_e_nao_zero_por_cento(self):
        """Se a API renomear os campos, o card não pode exibir 0% verde: tem de dizer que falhou."""
        for campo in ('currentValue', 'usage'):
            with self.subTest(campo=campo):
                payload = json.loads(json.dumps(RESPOSTA_REAL))
                del payload['data']['limits'][0][campo]
                with self.assertRaises(ValueError):
                    mod.zai_info(payload)

    def test_limite_nao_positivo_vira_erro(self):
        """`<= 0`, não `== 0`: quem rejeitasse só o zero deixaria o negativo virar percentual."""
        for limite in (0, -1, -2000):
            with self.subTest(usage=limite):
                payload = json.loads(json.dumps(RESPOSTA_REAL))
                payload['data']['limits'][0]['usage'] = limite   # 0 renderizaria "44/0"
                with self.assertRaises(ValueError):
                    mod.zai_info(payload)

    def test_updated_fica_vazio(self):
        # se voltar a carimbar o relógio local, o cache velho de outro vendor seria anunciado como
        # recém-lido no subtítulo global — e a suíte ficaria verde
        self.assertEqual(self.info['updated'], '')

    def test_payload_malformado_vira_erro(self):
        casos = {
            'corpo é lista': [],
            'corpo é string': 'ok',
            'data fora do tipo': {'success': True, 'data': 'lite'},
            'limits fora do tipo': {'success': True, 'data': {'limits': 'nenhum'}},
            'limits vazio': {'success': True, 'data': {'limits': []}},
            'janela não é objeto': {'success': True, 'data': {'limits': ['5h']}},
        }
        for nome, payload in casos.items():
            with self.subTest(caso=nome):
                with self.assertRaises(ValueError):
                    mod.zai_info(payload)


class TestGateHttp(unittest.TestCase):
    """A chamada precisa levar o header Bearer e o timeout — sem eles a API recusa."""

    def setUp(self):
        self.capturado = {}
        corpo = json.dumps(RESPOSTA_REAL).encode()
        self.patches = [
            mock.patch.object(mod, 'zai_api_key', return_value='chave-de-teste'),
            mock.patch.object(mod.urllib.request, 'urlopen',
                              fake_urlopen(corpo, self.capturado)),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_url_metodo_header_e_timeout(self):
        mod.run_zai()
        self.assertEqual(self.capturado['url'], mod.ZAI_URL)
        self.assertEqual(self.capturado['metodo'], 'GET')
        self.assertEqual(self.capturado['headers'].get('Authorization'), 'Bearer chave-de-teste')
        self.assertEqual(self.capturado['timeout'], 15)

    def test_envelope_de_sucesso(self):
        data = mod.run_zai()
        self.assertEqual(set(data), {'text', 'tooltip', 'class', 'info'})
        self.assertEqual(data['text'], '2,2%')                     # janela curta
        self.assertEqual(data['class'], mod.klass_of(44 / 2000 * 100))
        self.assertEqual(data['class'], 'low')
        self.assertFalse(mod.is_bad(data))
        self.assertEqual(data['info']['meters'][0]['name'], 'Sessão 5h')


class TestClassesDeErro(unittest.TestCase):
    """As cinco falhas percorrem run_zai() → is_bad() → offline_reason() com o mesmo contrato."""

    def _run_com(self, urlopen=None, chave='chave-de-teste'):
        patches = [mock.patch.object(mod, 'zai_api_key', return_value=chave)]
        if urlopen is not None:
            patches.append(mock.patch.object(mod.urllib.request, 'urlopen', urlopen))
        for p in patches:
            p.start()
        try:
            return mod.run_zai()
        finally:
            for p in patches:
                p.stop()

    def _confere(self, data, trecho_do_motivo):
        self.assertTrue(mod.is_bad(data), 'erro precisa cair na seção "sem configuração"')
        self.assertNotIn('info', data, 'erro não pode trazer info — viraria card com número falso')
        motivo, conserto = mod.offline_reason('zai', data)
        self.assertIn(trecho_do_motivo, motivo)
        self.assertEqual(conserto, '[zai] api_key')
        self.assertLess(len(motivo), 60, 'motivo tem de ser curto, não o traceback cru')

    def test_sem_chave(self):
        self._confere(self._run_com(chave=''), 'sem API key')

    def test_timeout(self):
        def estoura(req, timeout=None):
            raise TimeoutError('demorou')
        self._confere(self._run_com(estoura), 'tempo esgotado')

    def test_http_nao_200(self):
        def erro_http(req, timeout=None):
            raise mod.urllib.error.HTTPError(mod.ZAI_URL, 401, 'Unauthorized', {}, None)
        self._confere(self._run_com(erro_http), 'HTTP 401')

    def test_corpo_nao_e_json(self):
        def html(req, timeout=None):
            return FakeResposta(b'<html>portal cativo</html>')
        self._confere(self._run_com(html), 'não é JSON')

    def test_success_false(self):
        corpo = json.dumps({'code': 1000, 'msg': 'Authentication Failed',
                            'success': False}).encode()

        def recusa(req, timeout=None):
            return FakeResposta(corpo)
        self._confere(self._run_com(recusa), 'API recusou')

    def test_rede_indisponivel_nao_se_disfarca_de_timeout(self):
        # DNS/conexão recusada não é timeout: diagnóstico errado custa tempo de quem lê
        def sem_rede(req, timeout=None):
            raise mod.urllib.error.URLError('Name or service not known')
        data = self._run_com(sem_rede)
        self._confere(data, 'rede indisponível')
        self.assertNotIn('tempo esgotado', data['reason'])


class TestRoteamentoEGuarda(unittest.TestCase):
    """run_vendor('zai') é a promessa central; e nada pode escapar dele."""

    def test_run_vendor_roteia_zai_para_a_api(self):
        # sem esta asserção, trocar a condição para 'z.ai' deixaria os testes verdes e o card no
        # "0% · —" via subprocesso do ai-usagebar
        with mock.patch.object(mod, 'run_zai', return_value={'text': 'veio-da-api'}) as api, \
                mock.patch.object(mod.subprocess, 'check_output',
                                  side_effect=AssertionError('não deve chamar o ai-usagebar')):
            self.assertEqual(mod.run_vendor('zai'), {'text': 'veio-da-api'})
        api.assert_called_once_with()

    def test_run_vendor_nao_deixa_excecao_escapar(self):
        """Exceção escapando mata a thread do pool: o render nunca roda e o popup inteiro congela."""
        with mock.patch.object(mod, 'run_zai', side_effect=TypeError('inesperado')):
            data = mod.run_vendor('zai')
        self.assertTrue(mod.is_bad(data))
        self.assertIn('TypeError', data['reason'])
        self.assertEqual(mod.offline_reason('zai', data)[1], '[zai] api_key')

    def test_outros_vendors_nao_passam_pelo_desvio(self):
        with mock.patch.object(mod, 'run_zai', side_effect=AssertionError('desvio errado')), \
                mock.patch.object(mod.subprocess, 'check_output',
                                  return_value='{"text":"x","tooltip":"y","class":"low"}'):
            self.assertEqual(mod.run_vendor('anthropic')['class'], 'low')


class TestFormatacao(unittest.TestCase):
    def test_decimal_so_abaixo_de_dez(self):
        self.assertEqual(mod.fmt_pct(2.2), '2,2')
        self.assertEqual(mod.fmt_pct(0.44), '0,4')
        self.assertEqual(mod.fmt_pct(25), '25')      # inteiro dos outros vendors, inalterado
        self.assertEqual(mod.fmt_pct(23.7), '24')
        self.assertEqual(mod.fmt_pct(0), '0')
        self.assertEqual(mod.fmt_pct(9.96), '10')   # arredondar depois daria "10,0"

    def test_delta_tolera_timestamp_ausente(self):
        # nextResetTime nulo estourava TypeError e congelava o refresh de todos os vendors
        self.assertEqual(mod.fmt_delta(None), '—')
        self.assertEqual(mod.fmt_delta('ontem'), '—')

    def test_delta_no_padrao_dos_cards(self):
        agora = 1788565955.192
        with mock.patch.object(mod.time, 'time', return_value=agora):
            self.assertEqual(mod.fmt_delta((agora + 4 * 3600 + 31 * 60) * 1000), '4h 31m')
            self.assertEqual(mod.fmt_delta((agora + 2 * 86400 + 17 * 3600) * 1000), '2d 17h')
            self.assertEqual(mod.fmt_delta((agora + 12 * 60) * 1000), '12m')
            self.assertEqual(mod.fmt_delta((agora - 60) * 1000), 'agora')


class TestChave(unittest.TestCase):
    def test_config_toml_tem_precedencia_sobre_a_env(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as fh:
            fh.write('[zai]\napi_key = "do-config"\n')
            caminho = Path(fh.name)
        with mock.patch.object(mod, 'ZAI_CONFIG', caminho), \
                mock.patch.dict(mod.os.environ, {'ZAI_API_KEY': 'da-env'}):
            self.assertEqual(mod.zai_api_key(), 'do-config')
        caminho.unlink()

    def test_sem_config_cai_na_env(self):
        with mock.patch.object(mod, 'ZAI_CONFIG', Path('/nao/existe/config.toml')), \
                mock.patch.dict(mod.os.environ, {'ZAI_API_KEY': 'da-env'}):
            self.assertEqual(mod.zai_api_key(), 'da-env')

    def test_zai_como_string_no_toml_nao_estoura(self):
        # `zai = "chave"` em vez de `[zai]` é erro de digitação plausível
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as fh:
            fh.write('zai = "chave-solta"\n')
            caminho = Path(fh.name)
        with mock.patch.object(mod, 'ZAI_CONFIG', caminho), \
                mock.patch.dict(mod.os.environ, {'ZAI_API_KEY': 'da-env'}):
            self.assertEqual(mod.zai_api_key(), 'da-env')
        caminho.unlink()

    def test_sem_nada_devolve_vazio(self):
        with mock.patch.object(mod, 'ZAI_CONFIG', Path('/nao/existe/config.toml')), \
                mock.patch.dict(mod.os.environ, {}, clear=True):
            self.assertEqual(mod.zai_api_key(), '')


def _tem_display():
    return mod.Gtk.init_check([])[0]


@unittest.skipUnless(_tem_display(), 'precisa de display (rode sob Xvfb)')
class TestCard(unittest.TestCase):
    """Widgets exigem display; sob Xvfb estes casos rodam de verdade."""

    def setUp(self):
        self.win = mod.UsageWindow.__new__(mod.UsageWindow)

    def test_celula_minima_acende_com_uso_positivo(self):
        acesas = lambda pct: sum(  # noqa: E731
            1 for c in self.win._cells(pct).get_children()
            if 'on' in c.get_style_context().list_classes()
            or 'tip' in c.get_style_context().list_classes())
        self.assertEqual(acesas(0), 0)      # nada usado não acende nada
        self.assertEqual(acesas(2.2), 1)    # 2,2% acenderia zero sem a regra
        self.assertEqual(acesas(0.44), 1)
        self.assertEqual(acesas(25), 5)     # 25% segue em 5 células, como antes

    def test_make_card_usa_info_sem_reparsear_tooltip(self):
        data = {'text': '2,2%', 'tooltip': '', 'class': 'low', 'info': mod.zai_info(RESPOSTA_REAL)}
        with mock.patch.object(mod, 'parse_tooltip',
                               side_effect=AssertionError('não deve reparsear tooltip')):
            card = self.win.make_card('Z.AI', data)
        textos = []

        def varre(w):
            if isinstance(w, mod.Gtk.Label):
                textos.append(w.get_text())
            if isinstance(w, mod.Gtk.Container):
                for filho in w.get_children():
                    varre(filho)
        varre(card)
        self.assertIn('Z.AI', textos)
        self.assertIn('GLM Coding Lite', textos)
        self.assertIn('Sessão 5h', textos)
        self.assertIn('2,2%', textos)


if __name__ == '__main__':
    unittest.main()
