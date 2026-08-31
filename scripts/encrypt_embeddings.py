"""Criptografa embeddings faciais já gravados em texto claro.

A leitura no app aceita os dois formatos (lista legada e blob criptografado), então
este script é opcional - rode-o uma vez, depois de definir
`EMBEDDING_ENCRYPTION_KEY` no `.env`, para que o dado biométrico antigo também
fique criptografado em repouso.

Uso:
    python scripts/encrypt_embeddings.py --dry-run   # mostra o que faria
    python scripts/encrypt_embeddings.py             # aplica

Faça backup de `data/face_recognition.db` antes. Guarde junto o
`data/embedding_salt.key`: sem o salt e a chave, os embeddings não voltam.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import Embedding, db_manager  # noqa: E402
from app.security.crypto import get_embedding_cipher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="apenas relata quantos embeddings seriam criptografados"
    )
    args = parser.parse_args()

    cipher = get_embedding_cipher()
    if not cipher.enabled:
        print(
            "EMBEDDING_ENCRYPTION_KEY não está definida - nada a fazer.\n"
            "Defina a chave no .env antes de rodar este script."
        )
        return 1

    with db_manager.session() as session:
        rows = session.query(Embedding).all()
        plaintext = [r for r in rows if not isinstance(r.embedding_data, dict)]

        print(f"Total de embeddings: {len(rows)}")
        print(f"Em texto claro:      {len(plaintext)}")

        if not plaintext:
            print("Nada a fazer: todos já estão criptografados.")
            return 0

        if args.dry_run:
            print("--dry-run: nenhuma alteração gravada.")
            return 0

        for row in plaintext:
            row.embedding_data = cipher.encrypt(row.embedding_data)

        print(f"{len(plaintext)} embedding(s) criptografado(s).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
