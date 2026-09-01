"""Teste de navegador real (Playwright) para o escape de XSS no dashboard.

Por que este teste existe: a correção do achado F1 da auditoria
(`escapeHtml()` em dashboard.html/monitor.html) era a única mudança de
segurança sem cobertura automatizada — `tests/test_input_validation.py` cobre a
camada de entrada, mas nada provava que a *saída* está escapada de fato no
navegador.

O teste semeia o payload direto no banco, de propósito: a validação de entrada
recusaria esse nome hoje, e o objetivo aqui é verificar a camada de saída de
forma independente (é ela que protege bancos com dados legados, ou qualquer
caminho futuro que grave nome sem passar pelo schema).

Não roda na suíte principal: exige Playwright + Chromium, instalados em
`.venv-browser`. Ver `tests/browser/README.md`.

    .venv-browser/Scripts/python.exe -m pytest tests/browser -v
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

pytest.importorskip("playwright", reason="Playwright não instalado (ver tests/browser/README.md)")
from playwright.sync_api import sync_playwright  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

#: Playwright roda em venv próprio (.venv-browser), que não tem as dependências
#: da aplicação. O servidor sob teste sobe com o interpretador da aplicação:
#: defina APP_PYTHON se o seu não for o mesmo que roda a suíte principal.
APP_PYTHON = os.getenv("APP_PYTHON") or sys.executable

#: O payload seta uma global em vez de chamar alert(): um alert() só apareceria
#: como dialog, enquanto a global é verificável mesmo se o script rodar sem UI.
XSS_NAME = '<img src=x onerror="window.__xssFired=true">'
XSS_EMAIL = '<img src=x onerror="window.__xssFiredEmail=true">'


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_database(db_path: Path) -> None:
    """Grava um usuário com payload de XSS direto no banco, sem passar pela API."""
    env = dict(os.environ, DATABASE_PATH=str(db_path))
    code = f"""
from app.database.db import db_manager
user = db_manager.create_user(name={XSS_NAME!r}, email={XSS_EMAIL!r}, role="user")
db_manager.add_embedding(user_id=user.id, embedding_data=[0.1, 0.2], is_primary=True)
db_manager.log_access(user_id=user.id, action="recognition", status="success")
db_manager.log_presence(user_id=user.id, status="presente")
"""
    subprocess.run(
        [APP_PYTHON, "-c", code],
        cwd=PROJECT_ROOT, env=env, check=True,
        capture_output=True, text=True,
    )


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Sobe a aplicação real com banco temporário e a derruba no fim."""
    db_path = tmp_path_factory.mktemp("browser-db") / "test.db"
    port = _free_port()
    env = dict(
        os.environ,
        DATABASE_PATH=str(db_path),
        JWT_SECRET_KEY="chave-de-teste-para-browser-com-32-chars",
        ADMIN_PASSWORD="Str0ng!Passw0rd",
        ENVIRONMENT="development",
        PORT=str(port),
        # Dashboard e monitor fazem polling de 3 endpoints a cada 3-5 s: com o
        # limite padrão (100 req/min por IP), o próprio teste seria bloqueado com
        # 429 e as tabelas ficariam vazias. O rate limiter tem suíte própria
        # (tests/test_general_rate_limit.py); aqui ele só estorva.
        RATE_LIMIT_MAX_REQUESTS="100000",
    )

    _seed_database(db_path)

    # Log em arquivo, não em subprocess.PIPE: a aplicação loga cada requisição e
    # o buffer do pipe (sem ninguém lendo) enche e trava o servidor no meio da
    # sessão de testes.
    log_file = db_path.parent / "server.log"
    log_handle = log_file.open("w", encoding="utf-8", errors="replace")

    proc = subprocess.Popen(
        [APP_PYTHON, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=PROJECT_ROOT, env=env,
        stdout=log_handle, stderr=subprocess.STDOUT,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"servidor morreu ao subir:\n{log_file.read_text(errors='replace')}")
        try:
            urlopen(f"{base_url}/api/health", timeout=2).read()
            break
        except (URLError, OSError):
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail("servidor não respondeu em /api/health dentro do tempo limite")

    yield base_url, env

    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    log_handle.close()


def _admin_token(env: dict) -> str:
    """Gera um JWT de admin usando a mesma chave do servidor."""
    result = subprocess.run(
        [APP_PYTHON, "-c",
         "from app.security.auth import create_access_token;"
         "print(create_access_token({'sub': 'admin', 'role': 'admin'}))"],
        cwd=PROJECT_ROOT, env=env, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        instance = p.chromium.launch(
            headless=True,
            # O monitor só carrega presença/logs depois que a câmera inicia
            # (getUserMedia dentro de startMonitoring). A câmera fake do Chromium
            # deixa esse caminho rodar sem hardware e sem prompt de permissão.
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        )
        yield instance
        instance.close()


@pytest.fixture
def page_factory(live_server, browser):
    """Abre páginas autenticadas e as fecha ao fim de cada teste.

    Não se espera por `networkidle`: dashboard e monitor fazem polling contínuo
    (3-5 s), então a rede nunca fica ociosa e a espera estouraria o timeout.
    Cada teste aguarda o seletor concreto que lhe interessa.
    """
    base_url, env = live_server
    token = _admin_token(env)
    pages = []

    def open_page(path: str):
        page = browser.new_page()
        page.console_messages = []
        page.page_errors = []
        page.responses = []
        page.on("console", lambda m: page.console_messages.append(m))
        page.on("pageerror", lambda e: page.page_errors.append(str(e)))
        page.on("response", lambda r: page.responses.append((r.status, r.url)))
        # O dashboard redireciona para /login sem token no localStorage.
        page.add_init_script(f"localStorage.setItem('token', {json.dumps(token)});")
        # "load", não "domcontentloaded": os listeners de clique são registrados
        # dentro do handler de DOMContentLoaded, e com "domcontentloaded" o
        # Playwright libera antes desse handler rodar - o clique em #navUsers cai
        # no vazio. E não "networkidle": o polling contínuo nunca deixa a rede
        # ociosa.
        page.goto(f"{base_url}{path}", wait_until="load")
        pages.append(page)
        return page

    yield open_page

    for page in pages:
        page.close()


def _abrir_aba_usuarios(page_factory):
    """Abre a aba Usuários e espera a linha REAL, não o placeholder "Carregando...".

    Esperar só por `#usersTable tr` casaria com o placeholder e o teste passaria
    sem nada ter sido renderizado — falso negativo. O botão de excluir só existe
    em linha de dado de verdade.
    """
    page = page_factory("/dashboard")
    page.click("#navUsers")
    page.wait_for_selector("#usersTable [data-delete-user-id]")
    return page


def test_payload_no_nome_nao_executa_no_dashboard(page_factory):
    """Nenhum script do payload roda — resultado das DUAS camadas somadas.

    Verificado por mutação: removendo o `escapeHtml()` do nome, este teste
    continua passando, porque o CSP (`script-src` sem `'unsafe-inline'`) recusa
    o handler `onerror` injetado. Quem prova o escape em si é
    `test_payload_e_exibido_como_texto_literal`, que falha na mesma mutação.
    Os dois juntos é que dão a garantia: um cobre o outro.
    """
    page = _abrir_aba_usuarios(page_factory)
    page.wait_for_timeout(500)  # janela para um onerror disparar, se fosse o caso

    assert page.evaluate("window.__xssFired === undefined"), (
        "o payload no campo nome EXECUTOU no navegador — escape da saída falhou"
    )
    assert page.evaluate("window.__xssFiredEmail === undefined"), (
        "o payload no campo e-mail EXECUTOU no navegador"
    )


def test_payload_e_exibido_como_texto_literal(page_factory):
    """Prova do escape na saída: é este teste que quebra se `escapeHtml()` sair."""
    page = _abrir_aba_usuarios(page_factory)

    row = page.locator("#usersTable tr").first
    assert XSS_NAME in row.inner_text(), (
        "o nome deveria aparecer como texto literal na tabela"
    )
    # Nenhuma <img> injetada: o payload virou texto, não elemento.
    assert page.locator("#usersTable img").count() == 0


def test_payload_nao_executa_no_feed_de_logs(page_factory):
    """A aba inicial do dashboard já renderiza presença e logs de acesso."""
    page = page_factory("/dashboard")
    # Linha real de log tem 5 colunas; o placeholder tem uma só (colspan).
    page.wait_for_function(
        "document.querySelectorAll('#accessLogsTable tr td').length >= 5"
    )
    page.wait_for_timeout(500)

    assert page.evaluate("window.__xssFired === undefined")
    assert page.locator("#accessLogsTable img").count() == 0


def test_payload_nao_executa_no_monitor(page_factory):
    page = page_factory("/monitor")
    # Presença e logs só começam a carregar depois que o monitoramento inicia.
    page.click("#startBtn")
    page.wait_for_selector("#presenceList .presence-item")
    # state="attached": a aba de logs não é a ativa por padrão, então o elemento
    # existe no DOM mas não está visível - e o XSS executaria mesmo assim.
    page.wait_for_selector("#logList .log-item", state="attached")
    page.wait_for_timeout(500)

    assert page.evaluate("window.__xssFired === undefined")
    # O nome semeado aparece como texto, não como elemento injetado.
    assert XSS_NAME in page.locator("#presenceList .presence-name").first.inner_text()
    assert page.locator("#presenceList img").count() == 0
    assert page.locator("#logList img").count() == 0


def test_sem_violacao_de_csp_no_console(page_factory):
    """O CSP com nonce não pode estar bloqueando o script legítimo das páginas."""
    page = _abrir_aba_usuarios(page_factory)

    blocked = [
        m.text for m in page.console_messages
        if "content security policy" in m.text.lower()
        or "refused to execute" in m.text.lower()
    ]
    assert not blocked, f"CSP bloqueou script legítimo: {blocked}"
    assert not page.page_errors, f"erro de JS na página: {page.page_errors}"


def test_pagina_nao_depende_de_cdn_externo(page_factory):
    """Fonte e ícones vêm de app/static/vendor/, não de CDN.

    Antes o dashboard buscava a fonte Inter em fonts.googleapis.com e os ícones
    em cdnjs.cloudflare.com — interface sem ícone nenhum quando a rede local não
    tem internet, e um terceiro servindo CSS para a tela administrativa.
    """
    page = _abrir_aba_usuarios(page_factory)

    externos = [
        url for _, url in page.responses
        if not url.startswith(("http://127.0.0.1", "http://localhost", "data:", "blob:"))
    ]
    assert not externos, f"a página buscou recurso externo: {externos}"


def test_assets_locais_carregam_sem_404(page_factory):
    page = _abrir_aba_usuarios(page_factory)

    falhas = [
        (status, url) for status, url in page.responses
        if status >= 400 and "/static/" in url
    ]
    assert not falhas, f"asset local faltando: {falhas}"

    servidos = [url for _, url in page.responses if "/static/vendor/" in url]
    assert any("inter" in u for u in servidos), "fonte Inter local não foi carregada"
    assert any("fontawesome" in u for u in servidos), "Font Awesome local não foi carregado"
