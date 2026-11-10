"""Fechadura via serial: conexão, abertura, reconexão e modo desligado.

Antes, a linha que abria a serial estava comentada e `connect()` nunca era
chamado: o sistema logava "ABRINDO PORTA" e nenhum byte saía.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.services.hardware import CMD_CLOSE, CMD_OPEN, DoorController
from main import app


class SerialFalsa:
    def __init__(self, falhar_escrita: int = 0):
        self.is_open = True
        self.escritos: list[bytes] = []
        self.falhar_escrita = falhar_escrita

    def write(self, dado: bytes):
        if self.falhar_escrita:
            self.falhar_escrita -= 1
            self.is_open = False
            raise OSError("cabo desconectado")
        self.escritos.append(dado)

    def flush(self):
        pass

    def close(self):
        self.is_open = False


class Fabrica:
    """Cria SerialFalsa e registra cada conexão aberta."""

    def __init__(self, *conexoes: SerialFalsa, falhar: bool = False):
        self.fila = list(conexoes)
        self.abertas: list[SerialFalsa] = []
        self.falhar = falhar

    def __call__(self, port, baudrate):
        if self.falhar:
            raise OSError(f"could not open port {port}")
        conn = self.fila.pop(0) if self.fila else SerialFalsa()
        self.abertas.append(conn)
        return conn


def _porta(fabrica, enabled=True, **kw) -> DoorController:
    return DoorController(port="COM9", enabled=enabled, serial_factory=fabrica,
                          boot_seconds=0, **kw)


def _abrir_e_esperar(porta: DoorController, duration: int = 0) -> None:
    """Roda o ciclo de abertura de forma síncrona (sem a thread)."""
    porta._ciclo_abertura(duration)


def test_connect_abre_a_serial_e_trava():
    fabrica = Fabrica()
    porta = _porta(fabrica)

    assert porta.connect() is True
    assert porta.connected
    assert fabrica.abertas[0].escritos == [CMD_CLOSE]


def test_abrir_envia_O_e_depois_C():
    fabrica = Fabrica()
    porta = _porta(fabrica)
    porta.connect()

    _abrir_e_esperar(porta)

    assert fabrica.abertas[0].escritos == [CMD_CLOSE, CMD_OPEN, CMD_CLOSE]


def test_desligada_nao_abre_serial_nem_envia_nada():
    fabrica = Fabrica()
    porta = _porta(fabrica, enabled=False)

    assert porta.connect() is False
    _abrir_e_esperar(porta)

    assert fabrica.abertas == []
    assert porta.get_status() == {"enabled": False, "connected": False}


def test_sem_arduino_nao_derruba_e_reconecta_na_abertura_seguinte():
    fabrica = Fabrica(falhar=True)
    porta = _porta(fabrica)

    assert porta.connect() is False
    _abrir_e_esperar(porta)  # não levanta exceção
    assert not porta.connected

    fabrica.falhar = False  # Arduino plugado
    _abrir_e_esperar(porta)

    assert porta.connected
    assert fabrica.abertas[0].escritos == [CMD_CLOSE, CMD_OPEN, CMD_CLOSE]


def test_cabo_sai_entre_aberturas_e_reconecta_sozinho():
    primeira = SerialFalsa()
    segunda = SerialFalsa()
    fabrica = Fabrica(primeira, segunda)
    porta = _porta(fabrica)
    porta.connect()

    primeira.falhar_escrita = 1  # cabo saiu: a próxima escrita falha
    _abrir_e_esperar(porta)

    assert len(fabrica.abertas) == 2
    assert segunda.escritos == [CMD_CLOSE, CMD_OPEN, CMD_CLOSE]


def test_debounce_ignora_pedidos_repetidos(monkeypatch):
    porta = _porta(Fabrica())
    ciclos = []
    monkeypatch.setattr(porta, "_ciclo_abertura", lambda d: ciclos.append(d))
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())

    porta.open_door()
    porta.open_door()

    assert ciclos == [5]


def test_duracao_padrao_vem_da_configuracao(monkeypatch):
    porta = _porta(Fabrica(), open_seconds=1)
    ciclos = []
    monkeypatch.setattr(porta, "_ciclo_abertura", lambda d: ciclos.append(d))
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())

    porta.open_door()

    assert ciclos == [1]


def test_close_trava_e_solta_a_serial():
    fabrica = Fabrica()
    porta = _porta(fabrica)
    porta.connect()

    porta.close()

    assert fabrica.abertas[0].escritos == [CMD_CLOSE, CMD_CLOSE]
    assert not porta.connected


def test_from_settings_le_a_configuracao():
    from app.config import Settings

    s = Settings(door_enabled=True, door_serial_port="/dev/ttyUSB0",
                 door_baudrate=115200, door_open_seconds=1)
    porta = DoorController.from_settings(s)

    assert (porta.enabled, porta.port, porta.baudrate, porta.open_seconds) == (
        True, "/dev/ttyUSB0", 115200, 1)


@pytest.mark.parametrize("valor", [0, 31])
def test_open_seconds_fora_da_faixa_e_recusado(valor):
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(door_open_seconds=valor)


def test_health_mostra_a_porta_sem_expor_a_serial(monkeypatch):
    porta = _porta(Fabrica(falhar=True))
    monkeypatch.setattr(api_routes, "door_manager", porta)

    dados = TestClient(app).get("/api/health").json()

    assert dados["door"] == {"enabled": True, "connected": False}
    assert dados["status"] == "degraded"
    assert "COM9" not in str(dados)


def test_health_com_porta_desligada_nao_degrada_por_causa_dela(monkeypatch):
    monkeypatch.setattr(api_routes, "door_manager", _porta(Fabrica(), enabled=False))

    dados = TestClient(app).get("/api/health").json()

    assert dados["door"] == {"enabled": False, "connected": False}
