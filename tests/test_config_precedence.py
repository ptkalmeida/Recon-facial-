"""config.yaml precisa valer de verdade, e o ambiente precisa sobrepô-lo.

Antes: `app/config.py` carregava o YAML em `yaml_config` e nunca usava — editar
config.yaml não tinha efeito nenhum. O arquivo dizia `threshold: 0.3` enquanto o
valor em uso era 0.4. E `app/database/db.py` carregava o mesmo arquivo por conta
própria, em paralelo, com regras diferentes.

A precedência agora é: ambiente > .env > config.yaml > default do código.
"""

import textwrap

import pytest

from app.config import (
    YAML_PASSTHROUGH_SECTIONS,
    YAML_TO_FIELD,
    Settings,
    YamlConfigSource,
    settings,
    settings_dict,
)


@pytest.fixture
def yaml_temporario(tmp_path, monkeypatch):
    """Aponta o carregador de YAML para um arquivo controlado pelo teste."""
    def escrever(conteudo: str):
        arquivo = tmp_path / "config.yaml"
        arquivo.write_text(textwrap.dedent(conteudo), encoding="utf-8")
        import app.config as cfg
        monkeypatch.setattr(cfg, "load_yaml_config", lambda *a, **k: __import__(
            "yaml").safe_load(arquivo.read_text(encoding="utf-8")) or {})
        return arquivo
    return escrever


def test_valor_do_yaml_chega_nas_settings(yaml_temporario, monkeypatch):
    yaml_temporario("""
        face_recognition:
          threshold: 0.22
        security:
          auth_max_attempts: 9
    """)
    # Sem as variáveis correspondentes no ambiente, o YAML é quem manda.
    monkeypatch.delenv("FACE_THRESHOLD", raising=False)
    monkeypatch.delenv("AUTH_MAX_ATTEMPTS", raising=False)

    s = Settings(_env_file=None)

    assert s.face_threshold == 0.22
    assert s.auth_max_attempts == 9


def test_ambiente_sobrepoe_o_yaml(yaml_temporario, monkeypatch):
    yaml_temporario("""
        face_recognition:
          threshold: 0.22
    """)
    monkeypatch.setenv("FACE_THRESHOLD", "0.55")

    assert Settings(_env_file=None).face_threshold == 0.55


def test_default_do_codigo_quando_nao_ha_yaml_nem_ambiente(yaml_temporario, monkeypatch):
    yaml_temporario("{}")
    monkeypatch.delenv("FACE_THRESHOLD", raising=False)

    assert Settings(_env_file=None).face_threshold == 0.4


def test_lista_de_cors_do_yaml_vira_string(yaml_temporario, monkeypatch):
    yaml_temporario("""
        security:
          cors_origins:
            - "https://a.example"
            - "https://b.example"
    """)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)

    assert Settings(_env_file=None).allowed_origins == "https://a.example,https://b.example"


def test_chave_desconhecida_e_reportada_em_vez_de_ignorada(yaml_temporario):
    yaml_temporario("""
        face_recognition:
          parametro_que_nao_existe: 1
        secao_inventada:
          coisa: 2
    """)

    desconhecidas = YamlConfigSource(Settings).chaves_desconhecidas

    assert "face_recognition.parametro_que_nao_existe" in desconhecidas
    assert "secao_inventada.coisa" in desconhecidas


def test_config_yaml_do_projeto_nao_tem_chave_orfa():
    """Guarda contra alguém adicionar chave no YAML sem mapear (voltaria a ser decorativa)."""
    assert YamlConfigSource(Settings).chaves_desconhecidas == []


def test_secoes_so_do_yaml_chegam_ao_settings_dict():
    """`presence` e `anti_spoofing` são lidas direto do dicionário pelo código."""
    for secao in ("presence", "anti_spoofing"):
        assert secao in settings_dict, f"{secao} precisa chegar ao settings_dict"

    assert settings_dict["presence"]["timeout_seconds"] == 60
    assert settings_dict["anti_spoofing"]["enabled"] is True


def test_fonte_unica_de_caminho_do_banco():
    """db.py carregava config.yaml em paralelo; agora vem de app.config."""
    from app.database.db import db_manager

    assert db_manager.db_path == settings.database_path


def test_mapeamento_aponta_para_campos_que_existem():
    campos = set(Settings.model_fields)
    invalidos = {c for c in YAML_TO_FIELD.values() if c not in campos}

    assert not invalidos, f"YAML_TO_FIELD aponta para campo inexistente: {invalidos}"


def test_passthrough_nao_colide_com_mapeamento():
    mapeadas = {caminho[0] for caminho in YAML_TO_FIELD}
    colisao = set(YAML_PASSTHROUGH_SECTIONS) & mapeadas

    assert not colisao, f"seção não pode ser mapeada e passthrough ao mesmo tempo: {colisao}"
