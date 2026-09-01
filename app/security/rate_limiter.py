"""
API Rate Limiting Module

Provides rate limiting for API endpoints to prevent abuse and brute force attacks.
"""

import logging
import threading
import time
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RateLimitEntry:
    """Stores rate limit information for a client."""
    requests: int
    window_start: float
    blocked_until: float | None = None


class RateLimiter:
    """
    Token bucket / sliding window rate limiter.
    
    Supports:
    - Per-endpoint rate limiting
    - Per-client IP rate limiting
    - Automatic cleanup of old entries
    """
    
    def __init__(
        self,
        max_requests: int = None,
        window_seconds: int = None,
        block_duration_seconds: int = 300
    ):
        self.max_requests = max_requests or settings.rate_limit_max_requests
        self.window_seconds = window_seconds or settings.rate_limit_window_seconds
        self.block_duration = block_duration_seconds
        
        # Storage: {key: RateLimitEntry}
        self._storage: dict[str, RateLimitEntry] = {}
        self._lock = threading.Lock()
        
        # Statistics
        self._blocked_count = 0
        self._allowed_count = 0
    
    def is_allowed(self, key: str) -> tuple[bool, dict]:
        """
        Check if a request is allowed for the given key.
        
        Args:
            key: Unique identifier (e.g., "endpoint:client_ip")
            
        Returns:
            (is_allowed, metadata)
            metadata contains: remaining_requests, reset_time, retry_after
        """
        now = time.time()
        
        with self._lock:
            entry = self._storage.get(key)
            
            # Check if currently blocked
            if entry and entry.blocked_until and now < entry.blocked_until:
                self._blocked_count += 1
                retry_after = int(entry.blocked_until - now)
                return False, {
                    "remaining_requests": 0,
                    "reset_time": entry.blocked_until,
                    "retry_after": retry_after,
                    "limit": self.max_requests,
                    "blocked": True
                }
            
            # Create new entry or check window
            if not entry or (now - entry.window_start) > self.window_seconds:
                # New window
                entry = RateLimitEntry(
                    requests=1,
                    window_start=now,
                    blocked_until=None
                )
                self._storage[key] = entry
                self._allowed_count += 1
                
                return True, {
                    "remaining_requests": self.max_requests - 1,
                    "reset_time": now + self.window_seconds,
                    "retry_after": 0,
                    "limit": self.max_requests,
                    "blocked": False
                }
            
            # Within existing window
            entry.requests += 1
            
            if entry.requests > self.max_requests:
                # Block the client
                entry.blocked_until = now + self.block_duration
                self._blocked_count += 1
                
                logger.warning(
                    f"Rate limit exceeded for key={key}, "
                    f"blocking for {self.block_duration}s"
                )
                
                return False, {
                    "remaining_requests": 0,
                    "reset_time": entry.blocked_until,
                    "retry_after": self.block_duration,
                    "limit": self.max_requests,
                    "blocked": True
                }
            
            self._allowed_count += 1
            
            return True, {
                "remaining_requests": self.max_requests - entry.requests,
                "reset_time": entry.window_start + self.window_seconds,
                "retry_after": 0,
                "limit": self.max_requests,
                "blocked": False
            }
    
    def cleanup_old_entries(self, max_age_seconds: int = None) -> int:
        """
        Remove old entries to prevent memory leaks.
        
        Args:
            max_age_seconds: Remove entries older than this
            
        Returns:
            Number of entries removed
        """
        if max_age_seconds is None:
            max_age_seconds = self.window_seconds * 2
        
        now = time.time()
        removed = 0
        
        with self._lock:
            keys_to_remove = [
                key for key, entry in self._storage.items()
                if (now - entry.window_start) > max_age_seconds
                and (entry.blocked_until is None or now > entry.blocked_until)
            ]
            
            for key in keys_to_remove:
                del self._storage[key]
                removed += 1
        
        if removed > 0:
            logger.debug(f"Cleaned up {removed} old rate limit entries")
        
        return removed
    
    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "active_keys": len(self._storage),
                "blocked_requests": self._blocked_count,
                "allowed_requests": self._allowed_count,
                "max_requests_per_window": self.max_requests,
                "window_seconds": self.window_seconds
            }


# Global rate limiter instance
api_rate_limiter = RateLimiter()


# Specialized rate limiters for different endpoints
auth_rate_limiter = RateLimiter(
    max_requests=settings.auth_max_attempts,
    window_seconds=300,  # per 5 minutes
    block_duration_seconds=settings.auth_block_duration
)

recognition_rate_limiter = RateLimiter(
    max_requests=60,  # 60 requests
    window_seconds=60,  # per minute
    block_duration_seconds=60  # 1 min block
)


def get_client_ip(request) -> str:
    """IP do cliente, honrando cabeçalhos de proxy SÓ se o peer for confiável.

    Antes, `X-Forwarded-For` era aceito de qualquer origem. Como esse valor é a
    chave do rate limiter, qualquer cliente podia mandar um IP diferente a cada
    requisição e furar por completo o limite de 5 tentativas de login — brute
    force ilimitado contra o único login do sistema.

    Agora o cabeçalho só vale quando a conexão vem de um endereço listado em
    `TRUSTED_PROXIES` (vazio por padrão: sem proxy declarado, vale o IP real da
    conexão, que o cliente não escolhe).
    """
    from app.config import get_trusted_proxies

    peer = None
    if hasattr(request, "client") and request.client:
        peer = request.client.host

    if peer and peer in get_trusted_proxies():
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Primeiro da cadeia = cliente original.
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

    return peer or "unknown"


def create_rate_limit_key(endpoint: str, client_ip: str, user_id: str | None = None) -> str:
    """Create a unique key for rate limiting."""
    if user_id:
        return f"{endpoint}:user:{user_id}"
    return f"{endpoint}:ip:{client_ip}"
