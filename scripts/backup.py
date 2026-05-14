import os
import shutil
import zipfile
from datetime import datetime

def create_backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_v2_baseline_{timestamp}.zip"
    
    # Files to backup
    include_paths = [
        "app/",
        "data/face_recognition.db",
        "data/admin_auth.json",
        "data/crypto_salt.bin",
        "config.yaml",
        ".env",
        "main.py",
        "register.py",
        "remove.py",
        "setup.py",
        "utils.py",
        "requirements.txt",
        "VERSION"
    ]
    
    print(f"📦 Iniciando backup de segurança: {backup_name}")
    
    with zipfile.ZipFile(backup_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for path in include_paths:
            if os.path.isfile(path):
                zipf.write(path)
                print(f"  + Arquivo: {path}")
            elif os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zipf.write(file_path)
                print(f"  + Diretório: {path}")
                
    print(f"\n✅ Backup concluído com sucesso!")
    print(f"Destino: {os.path.abspath(backup_name)}")

if __name__ == "__main__":
    create_backup()
