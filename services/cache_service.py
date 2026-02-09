"""Redis caching service for hotel lookups"""

import json
import logging
import hashlib
from typing import Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import redis, but make it optional
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not installed. Caching will be disabled.")


class CacheService:
    """
    Redis-based caching service for hotel lookup results.
    
    Caches:
    - Full hotel lookup results (24 hour TTL by default)
    - Website search results (12 hour TTL)
    - Scrape results (6 hour TTL)
    
    Cache keys are generated from hotel name + address to ensure uniqueness.
    """
    
    # TTL values in seconds
    HOTEL_LOOKUP_TTL = 24 * 60 * 60  # 24 hours
    WEBSITE_SEARCH_TTL = 12 * 60 * 60  # 12 hours
    SCRAPE_RESULT_TTL = 6 * 60 * 60  # 6 hours
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None
        self._connected = False
        
    async def connect(self) -> bool:
        """Connect to Redis server"""
        if not REDIS_AVAILABLE:
            logger.info("Redis library not available, caching disabled")
            return False
            
        try:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self._client.ping()
            self._connected = True
            logger.info(f"Connected to Redis at {self.redis_url}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Caching disabled.")
            self._connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self._client:
            await self._client.close()
            self._connected = False
            logger.info("Disconnected from Redis")
    
    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected"""
        return self._connected and self._client is not None
    
    def _generate_cache_key(self, prefix: str, hotel_name: str, address: Optional[str] = None) -> str:
        """Generate a consistent cache key from hotel name and address"""
        # Normalize the input
        key_parts = [hotel_name.lower().strip()]
        if address:
            key_parts.append(address.lower().strip())
        
        # Create a hash for consistent key length
        raw_key = "|".join(key_parts)
        key_hash = hashlib.md5(raw_key.encode()).hexdigest()[:16]
        
        return f"hotel:{prefix}:{key_hash}"
    
    async def get_hotel_lookup(self, hotel_name: str, address: Optional[str] = None) -> Optional[dict]:
        """
        Get cached hotel lookup result.
        
        Returns:
            Cached result dict or None if not found/expired
        """
        if not self.is_connected:
            return None
            
        try:
            key = self._generate_cache_key("lookup", hotel_name, address)
            cached = await self._client.get(key)
            
            if cached:
                result = json.loads(cached)
                logger.info(f"Cache HIT for hotel lookup: {hotel_name}")
                # Add cache metadata
                result["_cached"] = True
                result["_cache_key"] = key
                return result
            
            logger.debug(f"Cache MISS for hotel lookup: {hotel_name}")
            return None
            
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None
    
    async def set_hotel_lookup(
        self, 
        hotel_name: str, 
        address: Optional[str], 
        result: dict,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache a hotel lookup result.
        
        Args:
            hotel_name: Name of the hotel
            address: Optional address string
            result: The lookup result to cache
            ttl: Time-to-live in seconds (default: 24 hours)
            
        Returns:
            True if cached successfully
        """
        if not self.is_connected:
            return False
            
        try:
            key = self._generate_cache_key("lookup", hotel_name, address)
            
            # Add cache timestamp
            cache_data = result.copy()
            cache_data["_cached_at"] = datetime.utcnow().isoformat()
            
            # Convert datetime objects to strings for JSON serialization
            if "last_checked" in cache_data:
                if hasattr(cache_data["last_checked"], "isoformat"):
                    cache_data["last_checked"] = cache_data["last_checked"].isoformat()
            
            await self._client.setex(
                key,
                ttl or self.HOTEL_LOOKUP_TTL,
                json.dumps(cache_data)
            )
            
            logger.info(f"Cached hotel lookup: {hotel_name} (TTL: {ttl or self.HOTEL_LOOKUP_TTL}s)")
            return True
            
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False
    
    async def get_website_search(self, hotel_name: str, city: Optional[str] = None) -> Optional[list]:
        """Get cached website search results"""
        if not self.is_connected:
            return None
            
        try:
            key = self._generate_cache_key("search", hotel_name, city)
            cached = await self._client.get(key)
            
            if cached:
                logger.info(f"Cache HIT for website search: {hotel_name}")
                return json.loads(cached)
            
            return None
            
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None
    
    async def set_website_search(
        self,
        hotel_name: str,
        city: Optional[str],
        results: list,
        ttl: Optional[int] = None
    ) -> bool:
        """Cache website search results"""
        if not self.is_connected:
            return False
            
        try:
            key = self._generate_cache_key("search", hotel_name, city)
            await self._client.setex(
                key,
                ttl or self.WEBSITE_SEARCH_TTL,
                json.dumps(results)
            )
            logger.info(f"Cached website search: {hotel_name}")
            return True
            
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False
    
    async def invalidate_hotel(self, hotel_name: str, address: Optional[str] = None) -> int:
        """
        Invalidate all cache entries for a hotel.
        
        Returns:
            Number of keys deleted
        """
        if not self.is_connected:
            return 0
            
        try:
            # Delete lookup cache
            lookup_key = self._generate_cache_key("lookup", hotel_name, address)
            search_key = self._generate_cache_key("search", hotel_name, address)
            
            deleted = await self._client.delete(lookup_key, search_key)
            logger.info(f"Invalidated cache for {hotel_name}: {deleted} keys deleted")
            return deleted
            
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return 0
    
    async def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        if not self.is_connected:
            return {"connected": False, "error": "Redis not connected"}
            
        try:
            info = await self._client.info("stats")
            dbsize = await self._client.dbsize()
            
            return {
                "connected": True,
                "total_keys": dbsize,
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "hit_rate": round(
                    info.get("keyspace_hits", 0) / 
                    max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0), 1) * 100,
                    2
                )
            }
            
        except Exception as e:
            logger.error(f"Redis stats error: {e}")
            return {"connected": False, "error": str(e)}


# Singleton instance
_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """Get the global cache service instance"""
    global _cache_service
    if _cache_service is None:
        from config import REDIS_URL
        _cache_service = CacheService(REDIS_URL)
    return _cache_service
