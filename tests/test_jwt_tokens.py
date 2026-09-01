"""Contrato dos tokens JWT.

Escrito junto da troca de python-jose por PyJWT: a biblioteca mudou, o
comportamento não pode mudar. Cobre também o que nenhum teste cobria antes —
token expirado, assinatura adulterada e troca de algoritmo.
"""

from datetime import timedelta

import jwt as pyjwt
import pytest

from app.security.auth import ALGORITHM, SECRET_KEY, create_access_token, decode_token


def test_token_ida_e_volta():
    token = create_access_token({"sub": "admin", "role": "admin", "id": 0})

    payload = decode_token(token)

    assert payload is not None
    assert payload["sub"] == "admin"
    assert payload["role"] == "admin"
    assert payload["id"] == 0
    assert "exp" in payload


def test_token_e_string():
    """PyJWT 2.x devolve str; python-jose também. Contrato mantido."""
    assert isinstance(create_access_token({"sub": "admin"}), str)


def test_token_expirado_e_recusado():
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(seconds=-10))

    assert decode_token(token) is None


def test_token_valido_dentro_do_prazo():
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(minutes=5))

    assert decode_token(token) is not None


def test_assinatura_adulterada_e_recusada():
    token = create_access_token({"sub": "admin", "role": "admin"})
    corpo, _, assinatura = token.rpartition(".")
    adulterado = corpo + "." + ("a" * len(assinatura))

    assert decode_token(adulterado) is None


def test_payload_adulterado_e_recusado():
    """Trocar role para admin sem a chave não pode funcionar."""
    # Chave errada, mas longa: o PyJWT avisa (InsecureKeyLengthWarning) para
    # chave HMAC com menos de 32 bytes, e não é isso que este teste investiga.
    forjado = pyjwt.encode(
        {"sub": "invasor", "role": "admin"},
        "chave-errada-mas-com-tamanho-suficiente-para-hs256",
        algorithm=ALGORITHM,
    )

    assert decode_token(forjado) is None


def test_algoritmo_none_e_recusado():
    """`alg: none` é o ataque clássico contra validação frouxa de JWT."""
    sem_assinatura = pyjwt.encode({"sub": "invasor", "role": "admin"}, key="", algorithm="none")

    assert decode_token(sem_assinatura) is None


def test_lixo_nao_derruba_o_decode():
    for entrada in ["", "abc", "a.b.c", "Bearer token", "." * 10]:
        assert decode_token(entrada) is None


def test_algoritmo_configurado_e_hs256():
    """HS256 com chave simétrica: `algorithms` fixo evita confusão de algoritmo."""
    assert ALGORITHM == "HS256"
    assert SECRET_KEY, "SECRET_KEY não pode ser vazia"

    cabecalho = pyjwt.get_unverified_header(create_access_token({"sub": "admin"}))
    assert cabecalho["alg"] == "HS256"
