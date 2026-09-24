"""Configuração inválida falha no boot, com o nome do campo, e não em produção.

Antes, um FACE_THRESHOLD=4 ou CONFIRMATION_MIN_FRAMES=0 digitado errado passava
calado e virava comportamento estranho (aceitar qualquer rosto, confirmar
sem nenhum frame). E uma chave com erro de digitação no config.yaml era
ignorada sem aviso na execução.
"""

import pytest
from pydantic import ValidationError

import app.config as cfg
from app.config import Settings


def _settings(**valores):
    return Settings(_env_file=None, **valores)


def test_padroes_sao_validos():
    _settings()


@pytest.mark.parametrize("campo, valor", [
    ("face_threshold", 4),                          # distância de cosseno vai até 2
    ("face_threshold", 0),
    ("door_min_confidence", 1.5),                   # confiança vai até 1
    ("face_detector_threshold", -0.1),
    ("face_recognition_confirmation_min_frames", 0),
    ("face_recognition_confirmation_window_seconds", 0),
    ("port", 70000),
    ("retention_access_log_days", -1),
    ("server_camera_interval_seconds", 0),
])
def test_valor_fora_da_faixa_falha_com_o_nome_do_campo(campo, valor):
    with pytest.raises(ValidationError) as exc:
        _settings(**{campo: valor})
    assert campo in str(exc.value)


def test_histerese_abaixo_do_limiar_estrito_falha():
    with pytest.raises(ValidationError, match="FACE_HOLD_THRESHOLD"):
        _settings(face_threshold=0.5, face_hold_threshold=0.4)


def test_chave_desconhecida_do_yaml_e_reportada(monkeypatch):
    monkeypatch.setattr(cfg, "load_yaml_config", lambda *a, **k: {
        "face_recognition": {"treshold": 0.3},       # erro de digitação
    })
    assert cfg.yaml_unknown_keys() == ["face_recognition.treshold"]


def test_config_yaml_do_projeto_nao_tem_chave_desconhecida():
    assert cfg.yaml_unknown_keys() == []
