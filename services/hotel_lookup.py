"""Main hotel lookup orchestration service"""

import logging
from typing import Optional, List
from datetime import datetime

from models import HotelSearchRequest, HotelInfoResponse, StatusEnum
from .web_search import WebSearchService
from .web_scraper import WebScraperService
from .ai_extractor import AIExtractorService

logger = logging.getLogger(__name__)


class HotelLookupService:
    """Orchestrates the full hotel information lookup process"""
    
    def __init__(self):
        self.search_service = WebSearchService()
        self.scraper_service = WebScraperService()
        self.ai_service = AIExtractorService()
    
    async def lookup_hotel(self, request: HotelSearchRequest) -> HotelInfoResponse:
        """
        Perform a complete hotel information lookup
        
        Process:
        1. Search for hotel's official website
        2. Scrape the website (including relevant subpages)
        3. Use AI to extract structured information
        4. Return consolidated results
        """
        response = HotelInfoResponse(
            search_name=request.name,
            search_address=self._build_address(request),
            last_checked=datetime.utcnow()
        )
        
        try:
            # Step 1: Find the hotel's website
            logger.info(f"Looking up: {request.name}")
            search_results = self.search_service.search_hotel_website(
                name=request.name,
                address=request.address,
                city=request.city,
                postcode=request.postcode
            )
            
            if not search_results:
                response.status = StatusEnum.NOT_FOUND
                response.errors.append("No search results found for this hotel")
                return response
            
            # Get the best non-aggregator result
            official_result = None
            for result in search_results:
                if not result.get("is_aggregator", True):
                    official_result = result
                    break
            
            if not official_result:
                # Fall back to first result if no non-aggregator found
                official_result = search_results[0]
                response.errors.append("Could not find official website, using best available result")
            
            website_url = official_result["url"]
            response.official_website = website_url
            response.website_source_url = "DuckDuckGo search"
            
            logger.info(f"Found website: {website_url}")
            
            # Step 2: Scrape the website
            scrape_result = await self.scraper_service.deep_scrape_hotel(website_url)
            
            if not scrape_result["success"]:
                response.status = StatusEnum.PARTIAL
                response.errors.append(f"Failed to scrape website: {website_url}")
                
                # Try booking sites as fallback
                booking_result = await self._try_booking_sites(request)
                if booking_result:
                    self._apply_booking_result(response, booking_result)
                
                return response
            
            # Check for domain parking (business may have closed)
            parking_check = self.scraper_service.detect_domain_parking(
                html=scrape_result.get("raw_html", ""),
                text_content=scrape_result["text_content"]
            )
            
            if parking_check["is_parked"]:
                logger.warning(f"Domain appears to be parked: {website_url}")
                response.status = StatusEnum.PARTIAL
                response.errors.append(f"Website appears to be a parked domain - business may have closed. Indicators: {', '.join(parking_check['indicators_found'][:3])}")
                response.official_website = None  # Clear the website since it's not useful
                
                # Try booking sites to get historical info
                booking_result = await self._try_booking_sites(request)
                if booking_result:
                    self._apply_booking_result(response, booking_result)
                    response.errors.append(f"Room count sourced from {booking_result.get('source', 'booking site')}")
                
                return response
            
            # Step 3: Verify this is the correct hotel
            website_verified = True
            if self.ai_service.is_configured:
                verification = await self.ai_service.verify_website_is_correct(
                    hotel_name=request.name,
                    hotel_address=self._build_address(request),
                    website_content=scrape_result["text_content"]
                )
                
                is_not_match = not verification.get("is_match", True)
                verification_confidence = verification.get("confidence", 0)
                
                if is_not_match:
                    website_verified = False
                    response.errors.append(f"Website may not match hotel: {verification.get('reason')}")
                    response.official_website = None  # Clear since it's wrong
                    
                    # If website clearly doesn't match (any confidence that it's wrong), try booking sites
                    if verification_confidence > 0.5:  # Lowered threshold
                        logger.info(f"Website verification failed with confidence {verification_confidence}, trying booking sites")
                        booking_result = await self._try_booking_sites(request)
                        if booking_result:
                            self._apply_booking_result(response, booking_result)
                            response.status = StatusEnum.PARTIAL
                            response.errors.append(f"Data sourced from {booking_result.get('source', 'booking site')} as fallback")
                            return response
                        else:
                            response.status = StatusEnum.NOT_FOUND
                            response.errors.append("Could not find hotel information from any source - hotel may have closed")
                            return response
            
            # Step 4: Extract information with AI (only if website was verified)
            extraction = await self.ai_service.extract_hotel_info(
                hotel_name=request.name,
                website_content=scrape_result["text_content"],
                phone_candidates=scrape_result["phone_numbers"],
                room_candidates=scrape_result["room_mentions"]
            )
            
            # Populate response from extraction
            response.rooms_min = extraction.get("rooms_min")
            response.rooms_max = extraction.get("rooms_max")
            response.uk_contact_phone = extraction.get("uk_phone")
            response.rooms_source_notes = extraction.get("rooms_source_notes")
            response.confidence_score = extraction.get("confidence")
            
            # Set phone source URL
            if response.uk_contact_phone:
                response.phone_source_url = website_url
            
            # Determine final status
            if response.rooms_min and response.uk_contact_phone:
                response.status = StatusEnum.SUCCESS
            elif response.rooms_min or response.uk_contact_phone:
                response.status = StatusEnum.PARTIAL
            else:
                response.status = StatusEnum.PARTIAL
                response.errors.append("Could not extract room count or phone number from website")
                
                # Try booking sites as last resort for room count
                if not response.rooms_min:
                    booking_result = await self._try_booking_sites(request)
                    if booking_result:
                        self._apply_booking_result(response, booking_result)
                        if response.rooms_min:
                            response.status = StatusEnum.PARTIAL
                            response.errors.append(f"Room count sourced from {booking_result.get('source', 'booking site')}")
            
            logger.info(f"Lookup complete for {request.name}: status={response.status}")
            return response
            
        except Exception as e:
            logger.error(f"Lookup error for {request.name}: {e}")
            response.status = StatusEnum.ERROR
            response.errors.append(str(e))
            return response
    
    async def lookup_batch(self, requests: List[HotelSearchRequest], delay_seconds: float = 2.0) -> List[HotelInfoResponse]:
        """
        Process multiple hotel lookups with delay between each.
        
        Args:
            requests: List of hotel search requests
            delay_seconds: Delay between each lookup to avoid rate limiting
        """
        import asyncio
        results = []
        for i, request in enumerate(requests):
            result = await self.lookup_hotel(request)
            results.append(result)
            # Add delay between requests (but not after the last one)
            if i < len(requests) - 1:
                logger.info(f"Completed {i+1}/{len(requests)}, waiting {delay_seconds}s before next...")
                await asyncio.sleep(delay_seconds)
        return results
    
    def _build_address(self, request: HotelSearchRequest) -> Optional[str]:
        """Build full address string from request components"""
        parts = []
        if request.address:
            parts.append(request.address)
        if request.city:
            parts.append(request.city)
        if request.postcode:
            parts.append(request.postcode)
        
        return ", ".join(parts) if parts else None
    
    async def _try_booking_sites(self, request: HotelSearchRequest) -> Optional[dict]:
        """
        Try to get hotel information from booking aggregator sites.
        Useful when the hotel's own website is down or doesn't have room info.
        """
        try:
            result = await self.scraper_service.scrape_booking_site_for_rooms(
                hotel_name=request.name,
                city=request.city,
                address=request.address
            )
            if result.get("success"):
                return result
        except Exception as e:
            logger.warning(f"Booking site lookup failed: {e}")
        return None
    
    def _apply_booking_result(self, response: HotelInfoResponse, booking_result: dict):
        """Apply results from booking site scraping to the response"""
        if booking_result.get("rooms_min"):
            response.rooms_min = booking_result["rooms_min"]
        if booking_result.get("rooms_max"):
            response.rooms_max = booking_result["rooms_max"]
        if booking_result.get("source_notes"):
            response.rooms_source_notes = booking_result["source_notes"]
        if booking_result.get("phone") and not response.uk_contact_phone:
            response.uk_contact_phone = booking_result["phone"]
            response.phone_source_url = booking_result.get("source", "Booking site")
