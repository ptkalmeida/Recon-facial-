"""Criptografia em repouso dos embeddings faciais (dado biométrico).

`EMBEDDING_ENCRYPTION_KEY` existia em `app/config.py`/`.env.example` desde a v2 mas
nunca era lida por ninguém: os embeddings ficavam em texto claro no SQLite. Este
módulo fecha essa lacuna.

Formato gravado na coluna JSON `embeddings.embedding_data`:

* chave configurada -> ``{"v": 1, "enc": "<token Fernet>"}``
* chave ausente      -> a própria lista de floats (comportamento legado)

A leitura aceita os dois formatos, então bancos criados antes desta mudança
continuam funcionando sem migração obrigatória (use
``scripts/encrypt_embeddings.py`` para criptografar o que já está gravado).
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - `cryptography` é dependência declarada
    HAS_CRYPTOGRAPHY = False

PBKDF2_ITERATIONS = 480_000
SALT_FILENAME = "embedding_salt.key"


class EmbeddingCipherError(RuntimeError):
    """Falha irrecuperável ao criptografar/descriptografar um embedding."""


def _salt_path() -> Path:
    """Salt fica ao lado do banco realmente em uso.

    O caminho vem de `db_manager.db_path` (import tardio: `db.py` também importa
    este módulo, mas só dentro dos métodos) para não haver risco de o salt ir para
    um diretório diferente do banco que ele protege.
    """
    try:
        from app.database.db import db_manager
        db_file = db_manager.db_path
    except Exception:  # pragma: no cover - fallback se o db ainda não subiu
        db_file = settings.database_path

    db_dir = Path(db_file).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / SALT_FILENAME


def _load_or_create_salt() -> bytes:
    salt_file = _salt_path()
    if salt_file.exists():
        salt = salt_file.read_bytes()
        if len(salt) == 16:
            return salt
        raise EmbeddingCipherError(
            f"{salt_file} está corrompido ({len(salt)} bytes, esperado 16). "
            "Restaure o arquivo original - sem ele os embeddings já gravados "
            "não podem ser descriptografados."
        )

    salt = os.urandom(16)
    salt_file.write_bytes(salt)
    # O salt não é secreto, mas perdê-lo torna os dados irrecuperáveis.
    logger.info("Salt de criptografia de embeddings criado em %s", salt_file)
    return salt


class EmbeddingCipher:
    """Cifra/decifra embeddings com Fernet (AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key_material: Optional[str] = None):
        self._key_material = (
            settings.embedding_encryption_key
            if key_material is None
            else key_material
        )
        self._fernet = None

        if not self._key_material:
            logger.warning(
                "EMBEDDING_ENCRYPTION_KEY não definida - embeddings faciais serão "
                "gravados em texto claro. Defina a variável no .env para "
                "criptografar o dado biométrico em repouso."
            )
            return

        if not HAS_CRYPTOGRAPHY:
            raise EmbeddingCipherError(
                "EMBEDDING_ENCRYPTION_KEY está definida mas o pacote "
                "`cryptography` não está instalado."
            )

        derived = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_load_or_create_salt(),
            iterations=PBKDF2_ITERATIONS,
        ).derive(self._key_material.encode("utf-8"))
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, embedding: List[float]) -> Any:
        """Recebe a lista de floats, devolve o valor a gravar na coluna JSON."""
        if not self.enabled:
            return embedding
        payload = json.dumps(embedding, separators=(",", ":")).encode("utf-8")
        token = self._fernet.encrypt(payload).decode("ascii")
        return {"v": 1, "enc": token}

    def decrypt(self, stored: Any) -> List[float]:
        """Aceita tanto o formato criptografado quanto a lista legada."""
        # Legado: gravado antes desta mudança, ou com a chave desativada.
        if not isinstance(stored, dict):
            return stored

        if "enc" not in stored:
            raise EmbeddingCipherError(
                f"Formato de embedding desconhecido: chaves {sorted(stored)}"
            )

        if not self.enabled:
            raise EmbeddingCipherError(
                "Há embeddings criptografados no banco mas "
                "EMBEDDING_ENCRYPTION_KEY não está definida."
            )

        try:
            plain = self._fernet.decrypt(stored["enc"].encode("ascii"))
        except InvalidToken as exc:
            raise EmbeddingCipherError(
                "Não foi possível descriptografar um embedding: "
                "EMBEDDING_ENCRYPTION_KEY ou o salt mudaram."
            ) from exc
        return json.loads(plain.decode("utf-8"))


#: Instância única usada pelo `db_manager`. Criada sob demanda para não derivar a
#: chave (480k iterações de PBKDF2) durante o import do módulo.
_cipher: Optional[EmbeddingCipher] = None


def get_embedding_cipher() -> EmbeddingCipher:
    global _cipher
    if _cipher is None:
        _cipher = EmbeddingCipher()
    return _cipher
