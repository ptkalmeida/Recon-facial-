"""O mesmo rosto não pode ser cadastrado sob dois nomes.

Com dois cadastros do mesmo rosto, o reconhecimento escolhe um deles e o log
de acesso registra a pessoa errada. O cadastro é recusado sempre (API: 409;
CLI: mensagem e nenhum usuário criado).
"""

import cv2
import numpy as np
import pytest

import register
from app.database.db import db_manager
from app.services.face_recognition import FaceRecognitionService
from tests.test_registration_dedup import (  # noqa: F401 - fixture
    _cadastrar,
    _png,
    _unitario,
    _vizinho,
    modelo_falso,
)

BACKEND = "insightface:buffalo_l"


def _servico() -> FaceRecognitionService:
    s = FaceRecognitionService({"face_recognition": {"threshold": 0.4}})
    s.embedding_backend = BACKEND
    return s


# --- find_identity_conflict ---------------------------------------------

def test_conflito_encontra_o_mais_proximo_abaixo_do_limiar():
    s = _servico()
    a, b = _unitario(20), _unitario(21)
    s.load_known_faces([
        {"user_id": 1, "user_name": "Ana", "embedding_data": a.tolist(), "model_used": BACKEND},
        {"user_id": 2, "user_name": "Bia", "embedding_data": b.tolist(), "model_used": BACKEND},
    ])

    conflito = s.find_identity_conflict(_vizinho(a, 0.10, seed=22))

    assert conflito is not None
    assert conflito[:2] == (1, "Ana")
    assert conflito[2] == pytest.approx(0.10, abs=1e-4)
    assert s.find_identity_conflict(_unitario(23)) is None


def test_conflito_usa_o_limiar_estrito_e_nao_a_histerese():
    s = _servico()
    a = _unitario(24)
    s.load_known_faces([{"user_id": 1, "user_name": "Ana",
                         "embedding_data": a.tolist(), "model_used": BACKEND}])
    # Entre threshold (0,4) e hold_threshold (0,55): não é a mesma pessoa.
    assert s.find_identity_conflict(_vizinho(a, 0.45, seed=25)) is None


def test_conflito_normaliza_o_embedding_salvo():
    """O cadastro da API grava a média de vetores unitários (norma < 1)."""
    s = _servico()
    a = _unitario(26)
    salvo = np.mean([a, _vizinho(a, 0.3, seed=27)], axis=0)
    assert np.linalg.norm(salvo) < 0.95
    s.load_known_faces([{"user_id": 1, "user_name": "Ana",
                         "embedding_data": salvo.tolist(), "model_used": BACKEND}])

    assert s.find_identity_conflict(a) is not None


def test_conflito_nao_se_aplica_no_modo_degradado():
    s = _servico()
    s.embedding_backend = FaceRecognitionService.HOG_EMBEDDING_BACKEND
    a = _unitario(28)
    s.load_known_faces([{"user_id": 1, "user_name": "Ana",
                         "embedding_data": a.tolist(), "model_used": None}])
    assert s.find_identity_conflict(a) is None


# --- API -----------------------------------------------------------------

def test_api_recusa_rosto_ja_cadastrado_com_outro_nome(modelo_falso):
    vetores, criados = modelo_falso
    vetores[30] = _unitario(30)
    vetores[31] = _vizinho(vetores[30], 0.15, seed=31)  # mesma pessoa, outra foto
    criados += ["Pessoa Original", "Pessoa Clone"]

    assert _cadastrar("Pessoa Original", [_png(30)], "203.0.113.160").status_code == 200
    r = _cadastrar("Pessoa Clone", [_png(31)], "203.0.113.161")

    assert r.status_code == 409
    assert "Pessoa Original" in r.json()["detail"]
    assert db_manager.get_user_by_name("Pessoa Clone") is None


def test_api_cadastra_rosto_diferente(modelo_falso):
    vetores, criados = modelo_falso
    vetores[32] = _unitario(32)
    vetores[33] = _unitario(33)
    criados += ["Pessoa Um", "Pessoa Dois"]

    assert _cadastrar("Pessoa Um", [_png(32)], "203.0.113.162").status_code == 200
    r = _cadastrar("Pessoa Dois", [_png(33)], "203.0.113.163")

    assert r.status_code == 200, r.text
    assert db_manager.get_user_by_name("Pessoa Dois") is not None


def test_api_sem_rosto_nao_cria_usuario(modelo_falso, monkeypatch):
    from app.api import routes as api_routes

    _vetores, criados = modelo_falso
    criados.append("Pessoa Sem Rosto")
    monkeypatch.setattr(api_routes.face_service, "detect_faces", lambda img: [])

    r = _cadastrar("Pessoa Sem Rosto", [_png(34)], "203.0.113.164")

    assert r.status_code == 400
    assert db_manager.get_user_by_name("Pessoa Sem Rosto") is None


# --- CLI (register.py) ---------------------------------------------------

@pytest.fixture
def cli(tmp_path, monkeypatch):
    """Serviço do CLI com embedding falso: a foto de marca N devolve VETORES[N]."""
    vetores: dict[int, np.ndarray] = {}
    chamadas: list[int] = []
    s = _servico()

    def registrar(img):
        chamadas.append(int(img[0, 0, 0]))
        return vetores[int(img[0, 0, 0])].copy()

    monkeypatch.setattr(s, "register_face", registrar)

    def foto(marca: int, nome: str) -> str:
        caminho = tmp_path / nome
        caminho.write_bytes(_png(marca))
        return str(caminho)

    criados: list[str] = []
    yield s, vetores, chamadas, foto, criados
    for nome in criados:
        user = db_manager.get_user_by_name(nome)
        if user:
            db_manager.delete_user(user.id)


def test_cli_ignora_arquivo_repetido(cli):
    s, vetores, chamadas, foto, _ = cli
    vetores[40] = _unitario(40)
    vetores[41] = _vizinho(vetores[40], 0.15, seed=41)
    p1, p2 = foto(40, "a.png"), foto(41, "b.png")
    copia = foto(40, "copia_de_a.png")

    resultado = register.process_images([p1, p2, p1, copia], s)

    assert resultado is not None
    assert sorted(chamadas) == [40, 41]


def test_cli_recusa_rosto_ja_cadastrado(cli):
    s, vetores, _chamadas, foto, criados = cli
    vetores[42] = _unitario(42)
    vetores[43] = _vizinho(vetores[42], 0.12, seed=43)
    criados += ["Cli Original", "Cli Clone"]

    assert register.register_person("Cli Original", None, [foto(42, "o.png")], s)
    assert not register.register_person("Cli Clone", None, [foto(43, "c.png")], s)
    assert db_manager.get_user_by_name("Cli Clone") is None


def test_cli_cadastra_rosto_diferente(cli):
    s, vetores, _chamadas, foto, criados = cli
    vetores[44] = _unitario(44)
    vetores[45] = _unitario(45)
    criados += ["Cli Um", "Cli Dois"]

    assert register.register_person("Cli Um", None, [foto(44, "u.png")], s)
    assert register.register_person("Cli Dois", None, [foto(45, "d.png")], s)


def test_png_de_teste_preserva_a_marca():
    img = cv2.imdecode(np.frombuffer(_png(77), np.uint8), cv2.IMREAD_COLOR)
    assert int(img[0, 0, 0]) == 77
