"""As quatro páginas saem dos templates, com o nonce do CSP no <script>.

O main.py tinha ~450 linhas de HTML embutido como "reserva" para quando
app/templates não existisse - desatualizado e sem nonce (não funcionava sob o
CSP). Template ausente agora responde 500 dizendo que a instalação está
incompleta.
"""

import re

import pytest
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


@pytest.mark.parametrize("caminho", ["/", "/monitor", "/dashboard", "/login"])
def test_pagina_sai_do_template(caminho):
    r = client.get(caminho, headers={"X-Forwarded-For": "203.0.113.160"})
    assert r.status_code == 200
    assert "Face Recognition" in r.text


@pytest.mark.parametrize("caminho", ["/monitor", "/dashboard", "/login"])
def test_script_leva_o_nonce_do_csp(caminho):
    r = client.get(caminho, headers={"X-Forwarded-For": "203.0.113.161"})
    nonce = re.search(r"'nonce-([^']+)'", r.headers["content-security-policy"]).group(1)
    assert f'<script nonce="{nonce}">' in r.text


def test_template_ausente_responde_500_explicito(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "templates_path", tmp_path)
    r = client.get("/dashboard", headers={"X-Forwarded-For": "203.0.113.162"})
    assert r.status_code == 500
    assert "Instalação incompleta" in r.text
