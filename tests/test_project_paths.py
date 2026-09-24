"""Caminhos da configuração são relativos à raiz do projeto, não ao CWD.

Antes, `data/face_recognition.db`, `logs/face_recognition.log` e
`data/admin_auth.json` eram resolvidos a partir do diretório atual. Rodar
`python C:\\...\\main.py` de outra pasta (atalho, serviço do Windows, agendador)
criava ali um banco novo e vazio — nenhum rosto cadastrado era reconhecido — e
um admin_auth.json novo a partir do .env, desfazendo a troca de senha feita pela
interface.
"""

from pathlib import Path

from app.config import PROJECT_ROOT, Settings, resolve_project_path


def test_relativo_vai_para_a_raiz_do_projeto():
    assert resolve_project_path("data/face_recognition.db") == str(
        PROJECT_ROOT / "data" / "face_recognition.db"
    )


def test_absoluto_e_memoria_ficam_intactos(tmp_path):
    absoluto = str(tmp_path / "banco.db")
    assert resolve_project_path(absoluto) == absoluto
    assert resolve_project_path(":memory:") == ":memory:"
    assert resolve_project_path("") == ""


def test_settings_ignoram_o_diretorio_atual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # simula atalho/serviço rodando de outra pasta

    s = Settings(
        _env_file=None,
        database_path="data/face_recognition.db",
        log_file="logs/face_recognition.log",
    )

    assert Path(s.database_path) == PROJECT_ROOT / "data" / "face_recognition.db"
    assert Path(s.log_file) == PROJECT_ROOT / "logs" / "face_recognition.log"
    assert not str(s.database_path).startswith(str(tmp_path))


def test_arquivo_de_admin_ancorado_na_raiz():
    from app.security.auth import auth_manager

    assert auth_manager.auth_file == PROJECT_ROOT / "data" / "admin_auth.json"


def test_suite_nunca_usa_o_banco_real():
    """Trava de segurança: a suíte roda num banco temporário (tests/conftest.py)."""
    from app.config import settings
    from app.database.db import db_manager

    banco_real = PROJECT_ROOT / "data"
    assert not Path(db_manager.db_path).resolve().is_relative_to(banco_real.resolve())
    assert not Path(settings.log_file).resolve().is_relative_to((PROJECT_ROOT / "logs").resolve())
