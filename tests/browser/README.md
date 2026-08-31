# Testes de navegador (Playwright)

Testes que sobem a aplicação de verdade e abrem o dashboard/monitor num Chromium
headless. Existem porque a correção de XSS do achado F1 da auditoria
(`escapeHtml()` nos templates) e o CSP com nonce só podem ser verificados num
navegador real — `TestClient` do FastAPI não executa JavaScript.

Ficam fora da suíte principal: exigem Playwright + Chromium (~115 MB) e levam
~15 s. `pytest tests/` normal ignora este diretório via `pytest.importorskip`.

## O que é coberto

| Teste | Verifica |
|---|---|
| `test_payload_no_nome_nao_executa_no_dashboard` | Nenhum script do payload roda (escape + CSP somados) |
| `test_payload_e_exibido_como_texto_literal` | O escape na saída, isoladamente |
| `test_payload_nao_executa_no_feed_de_logs` | Mesmo payload no feed de logs de acesso |
| `test_payload_nao_executa_no_monitor` | Lista de presença e feed de logs do monitor |
| `test_sem_violacao_de_csp_no_console` | O CSP não bloqueia recurso legítimo da página |

O payload é semeado **direto no banco**, de propósito: a validação de entrada
(`validate_person_name()`) recusaria esse nome hoje, e o objetivo é testar a
camada de saída de forma independente — é ela que protege bancos com dados
legados.

## Como rodar

Uma vez, para preparar o ambiente:

```bash
python -m venv .venv-browser
.venv-browser/Scripts/python.exe -m pip install playwright pytest
.venv-browser/Scripts/python.exe -m playwright install chromium
```

Depois:

```bash
# Windows (bash). APP_PYTHON = interpretador que tem as dependências da app;
# o venv do Playwright não as tem, e não precisa ter.
APP_PYTHON=/c/Python314/python.exe .venv-browser/Scripts/python.exe -m pytest tests/browser -v
```

```powershell
# PowerShell
$env:APP_PYTHON = "C:\Python314\python.exe"
.venv-browser\Scripts\python.exe -m pytest tests\browser -v
```

Se `APP_PYTHON` não for definida, usa-se o próprio interpretador do venv — o que
só funciona se ele tiver `fastapi`/`uvicorn`/`sqlalchemy` instalados.

## Armadilhas já resolvidas aqui

Anotadas porque cada uma custou uma rodada de depuração:

- **Não espere `networkidle`.** Dashboard e monitor fazem polling a cada 3-5 s, a
  rede nunca fica ociosa e a espera estoura o timeout.
- **Espere `load`, não `domcontentloaded`.** Os listeners de clique são
  registrados dentro do handler de `DOMContentLoaded`; com
  `domcontentloaded` o Playwright libera antes disso e o clique cai no vazio.
- **Não use `subprocess.PIPE` para o log do servidor.** A aplicação loga cada
  requisição, o buffer do pipe enche sem ninguém lendo e o servidor trava no meio
  da sessão. Redirecione para arquivo.
- **Suba o limite do rate limiter.** O polling das páginas passa de 100 req/min e
  o próprio teste é bloqueado com 429, deixando as tabelas vazias.
- **Espere o dado real, não o placeholder.** `#usersTable tr` casa com a linha
  "Carregando...", e o teste passa sem nada renderizado (falso negativo). Espere
  por `[data-delete-user-id]`.
- **O monitor precisa de câmera.** Presença e logs só carregam depois de
  `startMonitoring()`; use `--use-fake-device-for-media-stream`.
