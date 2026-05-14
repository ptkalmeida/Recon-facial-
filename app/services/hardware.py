import time
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Optional serial import for hardware control
try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    logger.warning("pyserial not available - hardware control disabled")

class DoorController:
    """
    Controlador de hardware para abertura de portas via Serial (Arduino/Relay).
    
    Inclui debounce para evitar ativações repetidas durante reconhecimento contínuo.
    """
    def __init__(self, port: str = "COM3", baudrate: int = 9600, timeout: int = 1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None
        self._lock = threading.Lock()
        self._last_open_time: float = 0.0

    def connect(self) -> bool:
        try:
            # Em um sistema real, aqui abriríamos a porta serial
            # self.connection = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            logger.info(f"Conectado ao controlador de porta em {self.port}")
            return True
        except Exception as e:
            logger.error(f"Erro ao conectar ao hardware da porta: {e}")
            return False

    def open_door(self, duration: int = 3):
        """
        Envia o comando de abertura para o hardware.
        
        Inclui debounce: ignora chamadas se a porta foi aberta recentemente.
        """
        # Debounce: skip if door was opened within (duration + 1) seconds
        now = time.time()
        if now - self._last_open_time < duration + 1:
            return
        self._last_open_time = now
        
        def trigger():
            # Use non-blocking acquire: if already opening, just skip this request
            if not self._lock.acquire(blocking=False):
                logger.debug("Porta já está em processo de abertura, ignorando comando redundante")
                return
                
            try:
                logger.info(">>> COMANDO: ABRINDO PORTA [ACESSO PERMITIDO] <<<")
                
                # Exemplo de comando Serial para Arduino: 'O' de OPEN
                if HAS_SERIAL and self.connection and hasattr(self.connection, 'is_open') and self.connection.is_open:
                    self.connection.write(b'O')
                
                # Mantém a porta aberta pelo tempo determinado
                time.sleep(duration)
                
                # Envia o comando de fechar: 'C' de CLOSE
                if HAS_SERIAL and self.connection and hasattr(self.connection, 'is_open') and self.connection.is_open:
                    self.connection.write(b'C')
                    
                logger.info(">>> COMANDO: PORTA FECHADA/TRAVADA <<<")
            except Exception as e:
                logger.error(f"Erro ao enviar comando para porta: {e}")
            finally:
                self._lock.release()

        # Executa em uma thread separada para não travar o reconhecimento facial
        threading.Thread(target=trigger, daemon=True).start()


# Instância global do controlador
door_manager = DoorController()
