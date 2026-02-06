"""
Hotel Information Extraction API

A FastAPI service that uses AI to extract hotel information (rooms, phone, website)
from hotel websites based on name and address.
"""

import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import LOG_LEVEL
from models import (
    HotelSearchRequest, 
    HotelInfoResponse, 
    HotelBatchRequest,
    BatchResponse,
    HealthResponse,
    StatusEnum
)
from services import HotelLookupService, AIExtractorService

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Service instances
lookup_service: HotelLookupService = None
ai_service: AIExtractorService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global lookup_service, ai_service
    
    logger.info("Starting Hotel Information API...")
    lookup_service = HotelLookupService()
    ai_service = AIExtractorService()
    
    if ai_service.is_configured:
        logger.info(f"AI Provider: {ai_service.get_provider_name()}")
    else:
        logger.warning("No AI provider configured! Set OPENAI_API_KEY or Azure OpenAI credentials.")
    
    yield
    
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


@app.post("/api/v1/hotel/lookup", response_model=HotelInfoResponse, tags=["Hotel Lookup"])
async def lookup_hotel(request: HotelSearchRequest):
    """
    Look up information for a single hotel.
    
    Provide the hotel name and optionally address/city/postcode to improve accuracy.
    
    The API will:
    1. Search for the hotel's official website
    2. Scrape the website for information
    3. Extract room count and contact phone using AI
    
    Returns structured data including confidence scores and source URLs.
    """
    if not lookup_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        result = await lookup_service.lookup_hotel(request)
        return result
    except Exception as e:
        logger.error(f"Lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/hotel/batch", response_model=BatchResponse, tags=["Hotel Lookup"])
async def lookup_batch(request: HotelBatchRequest):
    """
    Look up information for multiple hotels (max 100 per request).
    
    Each hotel in the batch will be processed sequentially to avoid rate limiting.
    For large batches, consider using the async endpoint instead.
    """
    if not lookup_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        results = await lookup_service.lookup_batch(request.hotels)
        
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
