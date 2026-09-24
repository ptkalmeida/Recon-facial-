"""Remoção de credenciais embutidas em URLs antes de irem para log ou resposta.

URLs de câmera IP carregam usuário e senha no próprio endereço
(`rtsp://admin:senha@192.168.1.10/stream`). Sem cuidado, a senha vaza para o
arquivo de log, para print de suporte e para respostas JSON — `/api/health`, que
não exige autenticação, devolvia a mensagem de erro da câmera com a URL inteira.
"""

import logging
import re

# `userinfo` guloso até o ÚLTIMO `@` do mesmo token (sem espaço): uma senha com
# `@` literal (`admin:p@ss@host`) é removida inteira, em vez de sobrar o pedaço
# depois do primeiro `@`. Remover a mais num caminho com `@` é aceitável; vazar
# parte da senha não é.
_URL_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^\s]*@")

REDACTED = "***"


def redact_url_credentials(text):
    """Troca o `usuario:senha@` de qualquer URL no texto por `***@`.

    Aceita qualquer objeto: não-strings são convertidas, `None` volta `None`.
    """
    if text is None:
        return None
    return _URL_USERINFO.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", str(text))


class CredentialRedactionFilter(logging.Filter):
    """Filtro de handler que aplica `redact_url_credentials` a todo registro.

    Instalado nos handlers (não num logger), porque filtro de logger não se
    aplica a registros que chegam por propagação de loggers-filhos — e é
    justamente de módulos quaisquer (`app.services...`) que a URL vaza.
    """

    _formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        # A mensagem é montada aqui (msg % args) para cobrir tanto f-string
        # quanto placeholders `%s`; depois os args são descartados para o
        # Formatter não remontar a versão original.
        try:
            mensagem = record.getMessage()
        except Exception:
            # Placeholders que não batem com os args: o logging padrão só
            # reportaria o erro, mas exceção dentro de filtro sobe para quem
            # chamou logger.info(). Registrar tudo cru (e redigido) é melhor.
            mensagem = f"{record.msg} {record.args}"
        record.msg = redact_url_credentials(mensagem)
        record.args = None

        # Traceback: a mensagem da exceção costuma repetir a URL. Pré-formatar
        # em `exc_text` faz o Formatter usar esta versão em vez de gerar outra.
        if record.exc_info and not record.exc_text:
            record.exc_text = self._formatter.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_url_credentials(record.exc_text)
        return True
