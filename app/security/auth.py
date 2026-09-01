import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# passlib removido: o CryptContext criado aqui não era usado por ninguém (as
# funções abaixo chamam bcrypt direto, justamente porque passlib 1.7.4 - último
# release em 2020 - quebra com bcrypt >= 4). Manter o import só somava uma
# dependência sem manutenção ao processo.


# Import secure settings
from app.config import settings

# Security configuration from environment variables
SECRET_KEY = settings.jwt_secret_key
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "SECURITY ERROR: JWT_SECRET_KEY must be set with at least 32 characters.\n"
        "Generate one with: openssl rand -base64 48\n"
        "Set it in the .env file."
    )
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
ADMIN_USERNAME = settings.admin_username


MAX_PASSWORD_LENGTH = 72  # bcrypt limit


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with bcrypt (truncated to 72 bytes)."""
    try:
        # Use raw bcrypt to avoid passlib compatibility issues with bcrypt 5.0.0+
        password_bytes = plain_password.encode('utf-8')[:MAX_PASSWORD_LENGTH]
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception as e:
        logger.error(f"Erro na verificação de senha: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Hash password with bcrypt (truncated to 72 bytes)."""
    # Use raw bcrypt to avoid passlib compatibility issues with bcrypt 5.0.0+
    password_bytes = password.encode('utf-8')[:MAX_PASSWORD_LENGTH]
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"Erro ao decodificar token: {e}")
        return None


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Authenticate user with secure password verification."""
    if username == ADMIN_USERNAME and auth_manager.verify_password(password):
        return {
            "id": 0,
            "username": username,
            "name": "Administrator",
            "role": "admin"
        }
    return None


def validate_password_strength(password: str) -> tuple[bool, str | None]:
    """Validate password strength.
    
    Returns: (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        return False, "Password must contain at least one special character"
    
    return True, None


class SimpleAuthManager:
    """Secure authentication manager with thread-safe in-memory rate limiting."""
    
    def __init__(self):
        self.auth_file = Path("data/admin_auth.json")
        self._lock = threading.RLock()
        self._initialized = False
        self._RATE_KEY = "admin_auth_attempts"
        self._ensure_auth_file()
        
    def _ensure_auth_file(self):
        with self._lock:
            if self._initialized:
                return
            
            os.makedirs(os.path.dirname(self.auth_file) if os.path.dirname(self.auth_file) else "data", exist_ok=True)
            
            if not self.auth_file.exists():
                current_password = settings.admin_password
                if not current_password:
                    raise RuntimeError(
                        "ADMIN_PASSWORD must be set before creating the admin auth file"
                    )

                is_strong, error = validate_password_strength(current_password)
                if not is_strong:
                    if settings.environment == "production":
                        raise RuntimeError(
                            f"ADMIN_PASSWORD does not meet strength requirements: {error}. "
                            "Set a stronger ADMIN_PASSWORD before starting in production."
                        )
                    logger.warning(
                        f"ADMIN_PASSWORD does not meet strength requirements: {error} "
                        "(allowed outside production, but change it before deploying)"
                    )

                default_data = {
                    "username": ADMIN_USERNAME,
                    "password_hash": get_password_hash(current_password),
                    "created_at": datetime.now().isoformat()
                }
                with open(self.auth_file, "w") as f:
                    json.dump(default_data, f, indent=2)
            
            self._initialized = True
    
    def is_blocked(self) -> tuple[bool, int]:
        """Check if authentication is blocked due to too many failed attempts.
        
        Uses thread-safe in-memory rate limiter instead of file-based tracking.
        
        Returns: (is_blocked, remaining_seconds)
        """
        from app.security.rate_limiter import auth_rate_limiter
        allowed, metadata = auth_rate_limiter.is_allowed(self._RATE_KEY)
        if not allowed:
            return True, metadata.get("retry_after", 0)
        return False, 0
                
    def verify_password(self, password: str) -> bool:
        """Verify password with thread-safe rate limiting and file locking."""
        from app.security.rate_limiter import auth_rate_limiter
        
        # Check rate limit (thread-safe)
        allowed, metadata = auth_rate_limiter.is_allowed(self._RATE_KEY)
        if not allowed:
            remaining = metadata.get("retry_after", 0)
            logger.warning(f"Authentication attempt blocked, {remaining}s remaining")
            return False
        
        with self._lock:
            self._ensure_auth_file()
            try:
                with open(self.auth_file, "r") as f:
                    data = json.load(f)
                
                is_valid = verify_password(password, data.get("password_hash", ""))
                
                if is_valid:
                    logger.info("Admin authenticated successfully")
                
                return is_valid
            except Exception as e:
                logger.error(f"Erro ao verificar senha: {e}")
                return False
            
    def change_password(self, new_password: str) -> tuple[bool, str | None]:
        """Change password with strength validation and thread-safe file access.
        
        Returns: (success, error_message)
        """
        # Validate password strength
        is_valid, error = validate_password_strength(new_password)
        if not is_valid:
            return False, error
        
        with self._lock:
            try:
                self._ensure_auth_file()
                with open(self.auth_file, "r") as f:
                    data = json.load(f)
                data["password_hash"] = get_password_hash(new_password)
                data["updated_at"] = datetime.now().isoformat()
                with open(self.auth_file, "w") as f:
                    json.dump(data, f, indent=2)
                logger.info("Admin password changed successfully")
                return True, None
            except Exception as e:
                logger.error(f"Erro ao alterar senha: {e}")
                return False, str(e)



auth_manager = SimpleAuthManager()

