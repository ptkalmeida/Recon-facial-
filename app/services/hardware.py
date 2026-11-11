"""Controle da fechadura física via Arduino + relé, pela porta serial (USB).

Protocolo (ver hardware/arduino/porta_rele/porta_rele.ino):
    b"O"  abre (energiza o relé)
    b"C"  trava

O Arduino também trava SOZINHO depois de alguns segundos aberto, mesmo sem
receber "C": se este processo travar ou o cabo sair no meio de uma abertura,
a porta não fica destravada para sempre.

Antes deste módulo, a linha que abria a serial estava comentada e `connect()`
nunca era chamado: o sistema logava "ABRINDO PORTA" e nenhum byte saía.
"""

import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    serial = None
    HAS_SERIAL = False
    logger.warning("pyserial não disponível - controle da porta física desativado")

CMD_OPEN = b"O"
CMD_CLOSE = b"C"

#: O Arduino reinicia quando a serial é aberta (sinal DTR) e leva ~1,5 s no
#: bootloader; um comando enviado antes disso se perde.
ARDUINO_BOOT_SECONDS = 2.0


def _abrir_serial(port: str, baudrate: int):
    return serial.Serial(port, baudrate, timeout=1, write_timeout=1)


class DoorController:
    """Aciona a fechadura. Seguro contra cabo desconectado e chamadas repetidas.

    - `enabled=False` (padrão): nada é enviado; a abertura só é registrada no
      log, como sempre foi.
    - Sem conexão no momento de abrir, tenta reconectar uma vez. Falhou: loga e
      segue - o reconhecimento nunca para por causa da porta.
    - Debounce: chamadas dentro de (duration + 1) s da última abertura são
      ignoradas - o reconhecimento contínuo pede abertura a cada frame.
    """

    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = 9600,
        enabled: bool = False,
        open_seconds: int = 5,
        serial_factory: Optional[Callable[[str, int], Any]] = None,
        boot_seconds: float = ARDUINO_BOOT_SECONDS,
    ):
        self.port = port
        self.baudrate = baudrate
        self.enabled = enabled
        self.open_seconds = open_seconds
        self.boot_seconds = boot_seconds
        self._serial_factory = serial_factory or (_abrir_serial if HAS_SERIAL else None)
        self.connection = None
        self._lock = threading.Lock()      # uma abertura por vez
        self._io_lock = threading.RLock()  # escrita/conexão na serial
        self._last_open_time: float = 0.0

    @classmethod
    def from_settings(cls, settings) -> "DoorController":
        return cls(
            port=settings.door_serial_port,
            baudrate=settings.door_baudrate,
            enabled=settings.door_enabled,
            open_seconds=settings.door_open_seconds,
        )

    # --- conexão ------------------------------------------------------------

    @property
    def connected(self) -> bool:
        conn = self.connection
        return conn is not None and bool(getattr(conn, "is_open", False))

    def connect(self) -> bool:
        """Abre a serial e garante a porta travada. False se não conseguir."""
        if not self.enabled:
            logger.info("Porta física desativada (door.enabled=false): aberturas só vão para o log")
            return False
        if self._serial_factory is None:
            logger.error("door.enabled=true mas o pyserial não está instalado (pip install pyserial)")
            return False
        with self._io_lock:
            self._descartar_conexao()
            try:
                conn = self._serial_factory(self.port, self.baudrate)
                time.sleep(self.boot_seconds)
                conn.write(CMD_CLOSE)
                conn.flush()
            except Exception as e:
                logger.error("Não foi possível conectar à porta física em %s: %s", self.port, e)
                return False
            self.connection = conn
            logger.info("Porta física conectada em %s (%d baud), travada", self.port, self.baudrate)
            return True

    def close(self) -> None:
        """Trava e solta a serial (desligamento do sistema)."""
        with self._io_lock:
            if self.connected:
                try:
                    self.connection.write(CMD_CLOSE)
                    self.connection.flush()
                except Exception as e:
                    logger.error("Erro ao travar a porta no desligamento: %s", e)
            self._descartar_conexao()

    def _descartar_conexao(self) -> None:
        conn, self.connection = self.connection, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def _send(self, comando: bytes) -> bool:
        """Envia um comando; reconecta uma vez se a conexão caiu."""
        with self._io_lock:
            for tentativa in (1, 2):
                if not self.connected and not self.connect():
                    return False
                try:
                    self.connection.write(comando)
                    self.connection.flush()
                    return True
                except Exception as e:
                    logger.error(
                        "Falha ao enviar %r para a porta física (tentativa %d): %s",
                        comando, tentativa, e,
                    )
                    self._descartar_conexao()
            return False

    def get_status(self) -> dict[str, bool]:
        """Para /api/health (público): só o estado, sem porta COM nem erro."""
        return {"enabled": self.enabled, "connected": self.connected}

    # --- abertura -----------------------------------------------------------

    def open_door(self, duration: Optional[int] = None) -> None:
        """Abre por `duration` segundos (padrão: door.open_seconds), sem bloquear."""
        duration = self.open_seconds if duration is None else duration
        now = time.time()
        if now - self._last_open_time < duration + 1:
            return
        self._last_open_time = now
        threading.Thread(target=self._ciclo_abertura, args=(duration,), daemon=True).start()

    def _ciclo_abertura(self, duration: int) -> None:
        if not self._lock.acquire(blocking=False):
            logger.debug("Porta já está em processo de abertura, ignorando comando redundante")
            return
        try:
            if not self.enabled:
                logger.info(">>> PORTA (simulação, door.enabled=false): ABRIR por %ss <<<", duration)
                return
            if not self._send(CMD_OPEN):
                logger.error(">>> PORTA NÃO ABERTA: sem comunicação com o controlador em %s <<<", self.port)
                return
            logger.info(">>> COMANDO: ABRINDO PORTA [ACESSO PERMITIDO] <<<")
            time.sleep(duration)
            if self._send(CMD_CLOSE):
                logger.info(">>> COMANDO: PORTA FECHADA/TRAVADA <<<")
            else:
                # O Arduino trava sozinho pelo tempo-limite dele.
                logger.error("Falha ao enviar o comando de travar; o Arduino trava pelo tempo-limite")
        finally:
            self._lock.release()


def _criar_door_manager() -> DoorController:
    from app.config import settings
    return DoorController.from_settings(settings)


# Instância global do controlador
door_manager = _criar_door_manager()
