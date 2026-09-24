"""Backup do que é preciso para restaurar a instalação.

Um restore só funciona com as peças juntas:

- o banco, copiado pela API de backup do SQLite: é uma cópia consistente mesmo
  com a aplicação rodando e, no modo WAL, inclui o que ainda está no arquivo
  `-wal` (copiar só o `.db` perderia essas transações);
- `embedding_salt.key` (ao lado do banco): sem ele, os embeddings cifrados não
  abrem e ninguém é reconhecido. A versão anterior deste script copiava
  `data/crypto_salt.bin`, que não existe, e deixava o salt de fora;
- `admin_auth.json` e `.env` - o `.env` contém segredos (JWT, senha do admin,
  EMBEDDING_ENCRYPTION_KEY): guarde o zip como segredo.

Uso: python scripts/backup.py

A saída é só texto (sem emoji): com stdout redirecionado - tarefa agendada,
pipe - o console do Windows usa cp1252 e um emoji derrubava o script antes de
gravar o backup.
"""

import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.security.crypto import SALT_FILENAME  # noqa: E402

# Código e configuração versionada, como no backup anterior.
ARQUIVOS_DO_PROJETO = [
    "app",
    "config.yaml",
    ".env",
    "data/admin_auth.json",
    "main.py",
    "register.py",
    "remove.py",
    "setup.py",
    "utils.py",
    "requirements.txt",
    "requirements-recognition.txt",
    "VERSION",
]


def _copiar_banco(origem: Path, destino: Path) -> None:
    """Cópia consistente (inclui o conteúdo do -wal) sem parar a aplicação."""
    # Conexão comum (a API de backup só lê a origem). Uma URI `mode=ro` quebra
    # com caminho do Windows com espaço e, com WAL, depende do arquivo -shm.
    fonte = sqlite3.connect(origem)
    try:
        alvo = sqlite3.connect(destino)
        try:
            fonte.backup(alvo)
        finally:
            alvo.close()
    finally:
        fonte.close()


def create_backup(banco: Path | None = None, destino: Path | None = None) -> Path:
    banco = Path(banco or settings.database_path)
    destino = Path(destino or PROJECT_ROOT)
    salt = banco.parent / SALT_FILENAME

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = destino / f"backup_{timestamp}.zip"
    print(f"Iniciando backup: {zip_path.name}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        if banco.exists():
            with tempfile.TemporaryDirectory() as tmp:
                copia = Path(tmp) / banco.name
                _copiar_banco(banco, copia)
                zipf.write(copia, f"data/{banco.name}")
            print(f"  + Banco (cópia consistente): {banco}")
        else:
            print(f"  ! Banco não encontrado: {banco}")

        if salt.exists():
            zipf.write(salt, f"data/{SALT_FILENAME}")
            print(f"  + Salt dos embeddings: {salt}")
        else:
            print("  ! Salt não encontrado - normal só se EMBEDDING_ENCRYPTION_KEY não estiver definida")

        for relativo in ARQUIVOS_DO_PROJETO:
            caminho = PROJECT_ROOT / relativo
            if caminho.is_file():
                zipf.write(caminho, relativo)
            elif caminho.is_dir():
                for arquivo in caminho.rglob("*"):
                    if arquivo.is_file() and "__pycache__" not in arquivo.parts:
                        zipf.write(arquivo, arquivo.relative_to(PROJECT_ROOT).as_posix())

    print("\nBackup concluído.")
    print(f"Destino: {zip_path}")
    print("ATENÇÃO: o zip contém o .env (segredos) e dados biométricos cifrados: guarde-o como segredo.")
    return zip_path


if __name__ == "__main__":
    create_backup()
