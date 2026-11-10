"""Teste de bancada da fechadura: aciona o relé sem câmera nem rosto.

Use na instalação, antes de ligar o reconhecimento:

    python scripts/test_door.py --list              # mostra as portas seriais
    python scripts/test_door.py --port COM4         # abre por door.open_seconds
    python scripts/test_door.py --port COM4 --seconds 1

Sem --port, usa door.serial_port do config.yaml / .env. Não precisa de
door.enabled=true: este script é justamente para testar antes de ligar.
Pare o servidor antes - duas conexões na mesma porta serial não funcionam.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.hardware import CMD_CLOSE, CMD_OPEN, HAS_SERIAL, DoorController  # noqa: E402


def listar_portas() -> int:
    from serial.tools import list_ports

    portas = list(list_ports.comports())
    if not portas:
        print("Nenhuma porta serial encontrada. O Arduino está conectado na USB?")
        return 1
    for p in portas:
        print(f"{p.device:<15} {p.description}")
    print("\nO Arduino costuma aparecer como 'Arduino', 'USB-SERIAL CH340' ou 'USB Serial Device'.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="lista as portas seriais e sai")
    parser.add_argument("--port", default=settings.door_serial_port)
    parser.add_argument("--baudrate", type=int, default=settings.door_baudrate)
    parser.add_argument("--seconds", type=int, default=settings.door_open_seconds)
    args = parser.parse_args()

    if not HAS_SERIAL:
        print("pyserial não instalado: pip install pyserial")
        return 1
    if args.list:
        return listar_portas()

    porta = DoorController(port=args.port, baudrate=args.baudrate, enabled=True)
    print(f"Conectando em {args.port} (o Arduino reinicia, ~2 s)...")
    if not porta.connect():
        print("Falhou. Confira a porta com --list e se o servidor está parado.")
        return 1

    try:
        porta.connection.reset_input_buffer()
        porta.connection.write(b"?")
        resposta = porta.connection.readline().decode(errors="replace").strip()
        print(f"Arduino respondeu: {resposta or '(nada - o sketch porta_rele.ino foi carregado?)'}")

        print(f"ABRINDO por {args.seconds} s - o relé deve clicar e a fechadura soltar.")
        porta._send(CMD_OPEN)
        time.sleep(args.seconds)
        porta._send(CMD_CLOSE)
        print("TRAVADA.")
    finally:
        porta.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
