"""
Hotel Information Extraction API

A FastAPI service that uses AI to extract hotel information (rooms, phone, website)
from hotel websites based on name and address.
"""

import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import LOG_LEVEL, REDIS_URL, REDIS_ENABLED
from models import (
    HotelSearchRequest, 
    HotelInfoResponse, 
    HotelBatchRequest,
    BatchResponse,
    HealthResponse,
    StatusEnum
)
from services import HotelLookupService, AIExtractorService
from services.cache_service import CacheService

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Service instances
lookup_service: HotelLookupService = None
ai_service: AIExtractorService = None
cache_service: CacheService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global lookup_service, ai_service, cache_service
    
    logger.info("Starting Hotel Information API...")
    
    # Initialize cache service
    cache_service = None
    if REDIS_ENABLED:
        cache_service = CacheService(REDIS_URL)
        connected = await cache_service.connect()
        if connected:
            logger.info(f"Redis caching enabled at {REDIS_URL}")
        else:
            logger.warning("Redis caching disabled (connection failed)")
            cache_service = None
    else:
        logger.info("Redis caching disabled by configuration")
    
    # Initialize lookup service with cache
    lookup_service = HotelLookupService(cache_service=cache_service)
    ai_service = AIExtractorService()
    
    if ai_service.is_configured:
        logger.info(f"AI Provider: {ai_service.get_provider_name()}")
    else:
        logger.warning("No AI provider configured! Set OPENAI_API_KEY or Azure OpenAI credentials.")
    
    yield
    
    # Cleanup
    if cache_service:
        await cache_service.disconnect()
    
    logger.info("Shutting down Hotel Information API...")


app = FastAPI(
    title="Hotel Information Extraction API",
    description="""
    An AI-powered API that extracts hotel information from websites.
    
    Given a hotel name and address, this API will:
    1. Search for the hotel's official website
    2. Scrape relevant pages for information
    3. Use AI to extract room counts and contact details
    
    ## Features
    - Automatic website discovery via web search
    - Deep scraping of hotel websites (homepage + subpages)
    - AI-powered information extraction
    - Phone number validation (UK format)
    - Confidence scoring
    
    ## Usage
    - **Single lookup**: POST /api/v1/hotel/lookup
    - **Batch lookup**: POST /api/v1/hotel/batch
    """,
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check API health and configuration status"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        ai_provider=ai_service.get_provider_name() if ai_service else "None",
        ai_configured=ai_service.is_configured if ai_service else False
    )


@app.get("/cache/stats", tags=["Cache"])
async def cache_stats():
    """Get Redis cache statistics"""
    if not cache_service:
        return {"enabled": False, "message": "Caching is disabled"}
    
    stats = await cache_service.get_cache_stats()
    return {"enabled": True, **stats}


@app.delete("/cache/invalidate", tags=["Cache"])
async def invalidate_cache(
    hotel_name: str = Query(..., description="Hotel name to invalidate cache for"),
    address: Optional[str] = Query(None, description="Optional address for more specific cache invalidation")
):
    """Invalidate cache for a specific hotel"""
    if not cache_service or not cache_service.is_connected:
        raise HTTPException(status_code=503, detail="Caching is not enabled or Redis is not connected")
    
    deleted = await cache_service.invalidate_hotel(hotel_name, address)
    return {"invalidated": True, "keys_deleted": deleted, "hotel_name": hotel_name}


@app.post("/api/v1/hotel/lookup", response_model=HotelInfoResponse, tags=["Hotel Lookup"])
async def lookup_hotel(
    request: HotelSearchRequest,
    skip_cache: bool = Query(False, description="Skip cache and force fresh lookup")
):
    """
    Look up information for a single hotel.
    
    Provide the hotel name and optionally address/city/postcode to improve accuracy.
    
    The API will:
    1. Check cache for existing result (unless skip_cache=true)
    2. Search for the hotel's official website
    3. Scrape the website for information
    4. Extract room count and contact phone using AI
    5. Cache the result for future lookups
    
    Returns structured data including confidence scores and source URLs.
    """
    if not lookup_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        result = await lookup_service.lookup_hotel(request, use_cache=not skip_cache)
        return result
    except Exception as e:
        logger.error(f"Lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/hotel/batch", response_model=BatchResponse, tags=["Hotel Lookup"])
async def lookup_batch(request: HotelBatchRequest):
    """
    Look up information for multiple hotels (max 100 per request).
    
    Hotels are processed in parallel (up to 5 concurrent) with rate limiting.
    
    **Performance estimates:**
    - 10 hotels: ~30-60 seconds
    - 20 hotels: ~1-2 minutes
    - 50 hotels: ~3-5 minutes
    
    **Scaling:**
    - Uses 5 concurrent lookups by default
    - Azure OpenAI quota: 500K TPM
    """
    if not lookup_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    # Adjust parallelism based on batch size
    if len(request.hotels) <= 10:
        max_concurrent = 4
        delay = 1.5
    elif len(request.hotels) <= 30:
        max_concurrent = 5
        delay = 1.5
    else:
        max_concurrent = 5
        delay = 2.0
        logger.info(f"Large batch of {len(request.hotels)} hotels - processing with 5 concurrent")
    
    try:
        results = await lookup_service.lookup_batch(
            request.hotels, 
            delay_seconds=delay,
            max_concurrent=max_concurrent
        )
        
        successful = sum(1 for r in results if r.status == StatusEnum.SUCCESS)
        partial = sum(1 for r in results if r.status == StatusEnum.PARTIAL)
        failed = sum(1 for r in results if r.status in [StatusEnum.NOT_FOUND, StatusEnum.ERROR])
        
        return BatchResponse(
            total_requested=len(request.hotels),
            successful=successful,
            partial=partial,
            failed=failed,
            results=results
        )
    except Exception as e:
        logger.error(f"Batch lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/hotel/example", response_model=HotelInfoResponse, tags=["Examples"])
async def example_response():
    """Get an example response showing the data structure"""
    return HotelInfoResponse(
        search_name="The Grand Hotel",
        search_address="1 King Street, Brighton, BN1 2FW",
        official_website="https://www.grandbrighton.co.uk",
        uk_contact_phone="+44 1273 224300",
        rooms_min=201,
        rooms_max=201,
        rooms_source_notes="Found on About page: 'The Grand Brighton boasts 201 luxurious bedrooms'",
        website_source_url="DuckDuckGo search",
        phone_source_url="https://www.grandbrighton.co.uk/contact",
        status=StatusEnum.SUCCESS,
        confidence_score=0.95,
        errors=[]
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
