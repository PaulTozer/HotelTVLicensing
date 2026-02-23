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

from config import LOG_LEVEL, REDIS_URL, REDIS_ENABLED, USE_BING_GROUNDING, BATCH_MAX_CONCURRENT, BATCH_MAX_SIZE
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
from services.bing_grounding_service import BingGroundingService

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
bing_service: BingGroundingService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global lookup_service, ai_service, cache_service, bing_service
    
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
    
    # Initialize Playwright service (lazy initialization on first use)
    from services.playwright_service import PLAYWRIGHT_AVAILABLE, get_playwright_service
    if PLAYWRIGHT_AVAILABLE:
        logger.info("Playwright available for JavaScript-rendered sites")
    else:
        logger.info("Playwright not available - JavaScript rendering disabled")
    
    # Initialize Bing Grounding service
    bing_service = None
    if USE_BING_GROUNDING:
        bing_service = BingGroundingService()
        if bing_service.is_configured:
            logger.info("Bing Grounding enabled (primary search method)")
        else:
            logger.warning("Bing Grounding not configured - falling back to SerpAPI/DuckDuckGo")
            bing_service = None
    else:
        logger.info("Bing Grounding disabled - using SerpAPI/DuckDuckGo")
    
    # Initialize lookup service with cache and Bing grounding
    lookup_service = HotelLookupService(
        cache_service=cache_service,
        bing_grounding_service=bing_service,
    )
    ai_service = AIExtractorService()
    
    if ai_service.is_configured:
        logger.info(f"AI Provider: {ai_service.get_provider_name()}")
    else:
        logger.warning("No AI provider configured! Set OPENAI_API_KEY or Azure OpenAI credentials.")
    
    yield
    
    # Cleanup
    if bing_service:
        await bing_service.cleanup_async()
    
    if cache_service:
        await cache_service.disconnect()
    
    # Cleanup Playwright
    if PLAYWRIGHT_AVAILABLE:
        try:
            playwright_service = get_playwright_service()
            await playwright_service.close()
        except Exception as e:
            logger.warning(f"Error closing Playwright: {e}")
    
    logger.info("Shutting down Hotel Information API...")


app = FastAPI(
    title="Hotel Information Extraction API",
    description="""
    An AI-powered API that extracts hotel information from websites.
    
    Given a hotel name and address, this API will:
    1. Search for the hotel using Azure AI Foundry agent with Bing Grounding
    2. Optionally scrape the official website for deeper information
    3. Use AI to extract room counts and contact details
    
    ## Features
    - **Bing Grounding** via Azure AI Foundry agent (primary search)
    - SerpAPI/DuckDuckGo fallback search
    - Deep scraping of hotel websites (homepage + subpages)
    - AI-powered information extraction
    - Phone number validation (UK format)
    - Confidence scoring
    - Redis caching
    
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
    search_provider = "Bing Grounding" if bing_service else "SerpAPI/DuckDuckGo"
    return HealthResponse(
        status="healthy",
        version="2.1.0",
        ai_provider=ai_service.get_provider_name() if ai_service else "None",
        ai_configured=ai_service.is_configured if ai_service else False,
        search_provider=search_provider,
    )


@app.get("/metrics", tags=["Health"])
async def get_metrics():
    """Get performance metrics for the Bing Grounding service"""
    bing_metrics = bing_service.metrics if bing_service else {}
    return {
        "bing_grounding": bing_metrics,
        "batch_config": {
            "max_concurrent_lookups": BATCH_MAX_CONCURRENT,
            "max_batch_size": BATCH_MAX_SIZE,
        },
    }


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
async def lookup_batch(
    request: HotelBatchRequest,
    fast: bool = Query(False, description="Fast mode: skip deep scraping, rely on Bing Grounding only. Much faster but may return more partial results."),
):
    """
    Look up information for multiple hotels in parallel.
    
    Hotels are processed concurrently with adaptive parallelism.
    The Bing Grounding agent handles up to 10 concurrent searches by default,
    while up to 25 full lookups can be in-flight simultaneously.
    
    **Performance estimates (with Bing Grounding):**
    - 25 hotels (fast mode): ~20-30 seconds
    - 25 hotels (full mode): ~60-120 seconds
    - 100 hotels (fast mode): ~1-2 minutes
    - 500 hotels (fast mode): ~5-10 minutes
    
    **Parameters:**
    - `fast=true`: Skip deep scraping for maximum throughput. Uses Bing Grounding only.
      Faster but may return more partial results for obscure hotels.
    
    **Scaling:**
    - 25 concurrent lookups (configurable via BATCH_MAX_CONCURRENT)  
    - 10 concurrent Bing searches (configurable via BING_MAX_CONCURRENT)
    - 20 threads for blocking SDK calls
    - Retry with exponential backoff for transient failures
    """
    if not lookup_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    import time
    start_time = time.time()
    
    try:
        results = await lookup_service.lookup_batch(
            request.hotels, 
            max_concurrent=BATCH_MAX_CONCURRENT,
            skip_deep_scrape=fast,
        )
        
        elapsed = time.time() - start_time
        successful = sum(1 for r in results if r.status == StatusEnum.SUCCESS)
        partial = sum(1 for r in results if r.status == StatusEnum.PARTIAL)
        failed = sum(1 for r in results if r.status in [StatusEnum.NOT_FOUND, StatusEnum.ERROR])
        
        return BatchResponse(
            total_requested=len(request.hotels),
            successful=successful,
            partial=partial,
            failed=failed,
            results=results,
            processing_time_seconds=round(elapsed, 1),
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
