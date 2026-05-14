import os
import json
import hashlib
import getpass
import secrets
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import bcrypt


def create_directories():
    dirs = ['data', 'logs', 'images']
    for d in dirs:
        Path(d).mkdir(exist_ok=True)
    print("Diretorios criados com sucesso!")


def generate_encryption_key(password: str, salt: bytes = None) -> tuple:
    if salt is None:
        salt = os.urandom(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key, salt


def setup_encryption():
    print("\n=== CONFIGURACAO DE CRIPTOGRAFIA ===")
    print("Crie uma senha mestra para criptografia do sistema.")
    print("ATENCAO: Esta senha NAO pode ser recuperada. Guarde-a com seguranca!")
    
    while True:
        password = getpass.getpass("Senha mestra: ")
        if len(password) < 8:
            print("Senha deve ter pelo menos 8 caracteres.")
            continue
        confirm = getpass.getpass("Confirme a senha: ")
        if password != confirm:
            print("Senhas diferentes. Tente novamente.")
            continue
        break
    
    key, salt = generate_encryption_key(password)
    
    salt_file = Path('data') / 'salt.key'
    with open(salt_file, 'wb') as f:
        f.write(salt)
    
    key_file = Path('data') / 'master.key'
    with open(key_file, 'wb') as f:
        f.write(key)
    
    print("Chave de criptografia gerada e salva!")





def init_database():
    print("\n=== INICIALIZANDO BANCO DE DADOS ===")
    
    conn = sqlite3.connect('data/logs.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS presence_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            type TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            action TEXT,
            ip TEXT,
            timestamp TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_presence_name ON presence_log(name)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_presence_date ON presence_log(date)
    ''')
    
    conn.commit()
    conn.close()
    
    print("Banco de dados inicializado!")





def create_sample_config():
    config = {
        'video_source': 0,
        'rtsp_url': '',
        'confidence_threshold': 0.6,
        'absence_timeout': 60,
        'detection_interval': 1,
        'log_rotation_days': 30,
        'rate_limit_max_attempts': 5,
        'rate_limit_block_duration': 900
    }
    
    import yaml
    with open('config.yaml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    print("Arquivo de configuracao criado!")


def main():
    print("=" * 50)
    print("  CONFIGURACAO DO SISTEMA DE RECONHECIMENTO FACIAL")
    print("=" * 50)
    
    create_directories()
    setup_encryption()
    init_database()
    create_sample_config()
    
    print("\n" + "=" * 50)
    print("  CONFIGURACAO CONCLUIDA COM SUCESSO!")
    print("=" * 50)
    print("\nProximos passos:")
    print("1. Configure o arquivo .env com JWT_SECRET_KEY e ADMIN_PASSWORD")
    print("2. Execute 'python register.py' para cadastrar pessoas")
    print("3. Execute 'python main.py' para iniciar o sistema")
    print("4. Use 'python export_logs.py' para exportar logs")


if __name__ == '__main__':
    main()