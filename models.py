"""Pydantic models for the Hotel Info API"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class StatusEnum(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"  # Some data found but not all
    NOT_FOUND = "not_found"
    ERROR = "error"


class HotelSearchRequest(BaseModel):
    """Request model for hotel information lookup"""
    name: str = Field(..., description="Hotel name", min_length=2)
    address: Optional[str] = Field(None, description="Hotel address (helps narrow down search)")
    city: Optional[str] = Field(None, description="City name")
    postcode: Optional[str] = Field(None, description="UK postcode")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "The Grand Hotel",
                "address": "1 King Street",
                "city": "Brighton",
                "postcode": "BN1 2FW"
            }
        }


class HotelBatchRequest(BaseModel):
    """Request model for batch hotel lookup"""
    hotels: List[HotelSearchRequest] = Field(..., min_length=1, max_length=500)


class HotelInfoResponse(BaseModel):
    """Response model with extracted hotel information"""
    # Input echo
    search_name: str
    search_address: Optional[str] = None
    
    # Extracted data
    official_website: Optional[str] = None
    uk_contact_phone: Optional[str] = None
    rooms_min: Optional[int] = None
    rooms_max: Optional[int] = None
    
    # Source tracking
    rooms_source_notes: Optional[str] = None
    website_source_url: Optional[str] = None
    phone_source_url: Optional[str] = None
    
    # Metadata
    status: StatusEnum = StatusEnum.NOT_FOUND
    last_checked: datetime = Field(default_factory=datetime.utcnow)
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="AI confidence in the extracted data")
    errors: List[str] = Field(default_factory=list)
    
    class Config:
        json_schema_extra = {
            "example": {
                "search_name": "The Grand Hotel",
                "search_address": "1 King Street, Brighton, BN1 2FW",
                "official_website": "https://www.grandbrighton.co.uk",
                "uk_contact_phone": "+44 1onal73 224300",
                "rooms_min": 201,
                "rooms_max": 201,
                "rooms_source_notes": "Found on hotel website About page: '201 luxurious bedrooms'",
                "website_source_url": "Bing Grounding",
                "phone_source_url": "https://www.grandbrighton.co.uk/contact",
                "status": "success",
                "last_checked": "2024-02-06T10:30:00Z",
                "confidence_score": 0.95,
                "errors": []
            }
        }


class BatchResponse(BaseModel):
    """Response model for batch requests"""
    total_requested: int
    successful: int
    partial: int
    failed: int
    processing_time_seconds: Optional[float] = None
    results: List[HotelInfoResponse]


class RetryItemResponse(BaseModel):
    """A single retry queue item"""
    id: str
    hotel_name: str
    address: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    original_errors: List[str] = Field(default_factory=list)
    original_status: str = "not_found"
    source_batch_id: Optional[str] = None
    status: str = "pending"
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: str
    last_attempt_at: Optional[str] = None
    next_retry_at: Optional[str] = None
    last_errors: List[str] = Field(default_factory=list)
    result: Optional[dict] = None


class RetryQueueStatsResponse(BaseModel):
    """Retry queue statistics"""
    queue_size: int
    pending: int
    retrying: int
    history_size: int
    total_succeeded: int
    total_exhausted: int
    storage: str
    max_attempts: int
    backoff_base_seconds: float
    is_processing: bool


class RetryAllResponse(BaseModel):
    """Response from processing all pending retries"""
    processed: int
    succeeded: int
    still_failed: int
    exhausted: int
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    ai_provider: str
    ai_configured: bool
    search_provider: str = "Unknown"
    retry_queue: Optional[str] = None
