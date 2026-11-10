"""scripts/evaluate_threshold.py: divisão sem vazamento e taxas corretas."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from tests.test_registration_dedup import _unitario, _vizinho

_spec = importlib.util.spec_from_file_location(
    "evaluate_threshold",
    Path(__file__).resolve().parent.parent / "scripts" / "evaluate_threshold.py",
)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def _fotos():
    ana, bia = _unitario(50), _unitario(51)
    return {
        "ana": {
            "s1": [ana, _vizinho(ana, 0.05, seed=52)],
            "s2": [_vizinho(ana, 0.20, seed=53), _vizinho(ana, 0.50, seed=54)],
        },
        "bia": {
            "s1": [bia],
            "s2": [_vizinho(bia, 0.10, seed=55)],
        },
        # Uma sessão só: entra como cadastro, não gera foto de teste.
        "caio": {"unica": [_unitario(56)]},
    }


def test_cadastro_e_teste_nunca_compartilham_sessao():
    divisao = ev.dividir(_fotos())

    assert set(divisao.cadastros) == {"ana", "bia", "caio"}
    for pessoa, sessao, _emb in divisao.sondas:
        assert sessao != divisao.sessao_cadastro[pessoa]
    assert len(divisao.sondas) == 3
    assert not any(p == "caio" for p, _, _ in divisao.sondas)


def test_primeira_sessao_em_ordem_alfabetica_e_o_cadastro():
    fotos = {"ana": {"b": [_unitario(60)], "a": [_unitario(61)]},
             "bia": {"x": [_unitario(62)]}}
    assert ev.dividir(fotos).sessao_cadastro["ana"] == "a"


def test_taxas_por_limiar():
    divisao = ev.dividir(_fotos())
    # Distâncias ao próprio cadastro das 3 fotos de teste: ~0.2, ~0.5 (ana) e
    # ~0.1 (bia). Aos outros cadastros: ~1 (vetores aleatórios em 512-d).
    r_03, r_06 = ev.avaliar(divisao, [0.3, 0.6])

    assert r_03.sondas == 3
    assert r_03.falsa_rejeicao == pytest.approx(1 / 3)  # a foto a 0.5 da ana
    assert r_06.falsa_rejeicao == 0.0
    assert r_03.troca_identidade == 0.0
    assert r_03.falsa_aceitacao == 0.0


def test_estranho_parecido_conta_como_aceito_e_como_troca():
    ana = _unitario(70)
    gemea = _vizinho(ana, 0.15, seed=71)
    fotos = {
        "ana": {"s1": [ana], "s2": [_vizinho(ana, 0.30, seed=72)]},
        "gemea": {"s1": [gemea], "s2": [_vizinho(gemea, 0.05, seed=73)]},
    }
    (r,) = ev.avaliar(ev.dividir(fotos), [0.4])

    # A foto de teste da gêmea fica a ~0.05 dela e a ~0.15 da ana: sem a
    # gêmea cadastrada, ela seria aceita como ana.
    assert r.falsa_aceitacao > 0
    assert r.falsa_rejeicao == 0.0


def test_thresholds_padrao_incluem_o_atual():
    valores = ev._thresholds_padrao(0.42)
    assert 0.42 in valores and valores[0] == pytest.approx(0.20)
    assert np.isclose(valores[-1], 0.70)
