import os
import sys
import json
import sqlite3
import numpy as np
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import CryptoManager, EncodingManager, DatabaseManager as LegacyDB
from app.database.db import db_manager, User, Embedding, AccessLog, PresenceRecord
from app.config import settings_dict

def migrate():
    load_dotenv()
    print("=== MIGRATION V1 -> V2 ===")
    
    # 1. Migrate Encodings
    encoding_file = 'data/encodings.enc'
    salt_file = 'data/crypto_salt.bin'
    
    if os.path.exists(encoding_file) and os.path.exists(salt_file):
        print("\n[1/3] Migrating Encodings...")
        
        with open(salt_file, 'rb') as f:
            salt = f.read()
            
        password = os.environ.get('EMBEDDING_ENCRYPTION_KEY') or os.environ.get('SYSTEM_PASSWORD')
        if not password:
            print("❌ Error: SYSTEM_PASSWORD/EMBEDDING_ENCRYPTION_KEY not found in .env")
            return

        try:
            crypto = CryptoManager(password, salt)
            encoding_mgr = EncodingManager(encoding_file, crypto)
            all_encodings = encoding_mgr.get_all_encodings()
            
            migrated_count = 0
            for name, data in all_encodings.items():
                # Check if user exists
                user = db_manager.get_user_by_name(name)
                if not user:
                    user = db_manager.create_user(name=name)
                    print(f"   + Created user: {name}")
                
                # Check if embedding already exists (avoid duplicates)
                with db_manager.session() as session:
                    exists = session.query(Embedding).filter(
                        Embedding.user_id == user.id,
                        Embedding.is_primary == True
                    ).first()
                    
                    if not exists:
                        db_manager.add_embedding(
                            user_id=user.id,
                            embedding_data=data['encoding'],
                            model_used=settings_dict.get("face_recognition", {}).get("model", "Facenet512"),
                            is_primary=True
                        )
                        migrated_count += 1
            
            print(f"✅ Migrated {migrated_count} encodings.")
        except Exception as e:
            print(f"❌ Error migrating encodings: {e}")
    else:
        print("\n[1/3] No legacy encodings found. Skipping.")

    # 2. Migrate Presence Logs
    legacy_db_path = 'data/logs.db'
    if os.path.exists(legacy_db_path):
        print("\n[2/3] Migrating Presence Logs...")
        try:
            conn = sqlite3.connect(legacy_db_path)
            cursor = conn.cursor()
            
            # Legacy schema: (id, name, date, time, type, created_at)
            cursor.execute("SELECT name, date, time, type, created_at FROM presence_log")
            rows = cursor.fetchall()
            
            migrated_count = 0
            for name, date_str, time_str, log_type, created_at in rows:
                user = db_manager.get_user_by_name(name)
                if not user:
                    continue # Should have been created above
                
                # Check if record exists (approximate by timestamp/user/type)
                dt = datetime.fromisoformat(created_at) if created_at else datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                
                with db_manager.session() as session:
                    # Map 'entrada'/'saida' status
                    status = "entrada" if log_type.lower() in ["entry", "entrada"] else "saida"
                    
                    # Add to PresenceRecord
                    record = PresenceRecord(
                        user_id=user.id,
                        status=status,
                        camera_source="legacy_migration",
                        created_at=dt
                    )
                    if status == "entrada":
                        record.check_in = dt
                    else:
                        record.check_out = dt
                        
                    session.add(record)
                    migrated_count += 1
            
            print(f"✅ Migrated {migrated_count} presence logs.")
            conn.close()
        except Exception as e:
            print(f"❌ Error migrating presence logs: {e}")
    else:
        print("\n[2/3] No legacy logs.db found. Skipping.")

    # 3. Migrate Access Logs
    if os.path.exists(legacy_db_path):
        print("\n[3/3] Migrating Access Logs...")
        try:
            conn = sqlite3.connect(legacy_db_path)
            cursor = conn.cursor()
            
            # Legacy schema: (id, user, action, ip, timestamp)
            cursor.execute("SELECT user, action, ip, timestamp FROM access_log")
            rows = cursor.fetchall()
            
            migrated_count = 0
            for username, action, ip, timestamp in rows:
                user_id = None
                if username and username != 'admin':
                    user = db_manager.get_user_by_name(username)
                    if user:
                        user_id = user.id
                
                dt = datetime.fromisoformat(timestamp) if timestamp else datetime.now()
                
                with db_manager.session() as session:
                    log = AccessLog(
                        user_id=user_id,
                        action=action,
                        status="success",
                        camera_source="legacy_migration",
                        ip_address=ip,
                        created_at=dt
                    )
                    session.add(log)
                    migrated_count += 1
            
            print(f"✅ Migrated {migrated_count} access logs.")
            conn.close()
        except Exception as e:
            print(f"❌ Error migrating access logs: {e}")

    print("\n=== MIGRATION COMPLETE ===")

if __name__ == "__main__":
    migrate()
