"""Main hotel lookup orchestration service"""

import logging
from typing import Optional, List
from datetime import datetime

from models import HotelSearchRequest, HotelInfoResponse, StatusEnum
from .web_search import WebSearchService
from .web_scraper import WebScraperService
from .ai_extractor import AIExtractorService
from .planning_portal import PlanningPortalService
from .cache_service import CacheService
from .bing_grounding_service import BingGroundingService

logger = logging.getLogger(__name__)


class HotelLookupService:
    """Orchestrates the full hotel information lookup process"""
    
    def __init__(self, cache_service: Optional[CacheService] = None, 
                 bing_grounding_service: Optional[BingGroundingService] = None):
        self.bing_service = bing_grounding_service
        self.search_service = WebSearchService()  # Fallback only
        self.scraper_service = WebScraperService()
        self.ai_service = AIExtractorService()
        self.planning_service = PlanningPortalService()
        self.cache_service = cache_service
    
    async def lookup_hotel(self, request: HotelSearchRequest, use_cache: bool = True) -> HotelInfoResponse:
        """
        Perform a complete hotel information lookup
        
        Process:
        1. Check cache for existing result
        2. Search for hotel's official website
        3. Scrape the website (including relevant subpages)
        4. Use AI to extract structured information
        5. Cache and return consolidated results
        """
        address_str = self._build_address(request)
        
        # Step 0: Check cache first
        if use_cache and self.cache_service and self.cache_service.is_connected:
            cached_result = await self.cache_service.get_hotel_lookup(request.name, address_str)
            if cached_result:
                logger.info(f"Returning cached result for: {request.name}")
                # Convert back to HotelInfoResponse
                response = HotelInfoResponse(
                    search_name=cached_result.get("search_name", request.name),
                    search_address=cached_result.get("search_address"),
                    official_website=cached_result.get("official_website"),
                    uk_contact_phone=cached_result.get("uk_contact_phone"),
                    rooms_min=cached_result.get("rooms_min"),
                    rooms_max=cached_result.get("rooms_max"),
                    rooms_source_notes=cached_result.get("rooms_source_notes"),
                    website_source_url=cached_result.get("website_source_url"),
                    phone_source_url=cached_result.get("phone_source_url"),
                    status=StatusEnum(cached_result.get("status", "partial")),
                    last_checked=datetime.fromisoformat(cached_result["last_checked"]) if cached_result.get("last_checked") else datetime.utcnow(),
                    confidence_score=cached_result.get("confidence_score"),
                    errors=cached_result.get("errors", [])
                )
                # Mark as cached
                response.errors.insert(0, f"[Cached result from {cached_result.get('_cached_at', 'unknown')}]")
                return response
        
        response = HotelInfoResponse(
            search_name=request.name,
            search_address=address_str,
            last_checked=datetime.utcnow()
        )
        
        try:
            # Step 1: Try Bing Grounding Agent first (primary search method)
            bing_result = None
            if self.bing_service and self.bing_service.is_configured:
                logger.info(f"Using Bing Grounding agent for: {request.name}")
                bing_result = await self.bing_service.search_hotel_async(
                    name=request.name,
                    address=request.address,
                    city=request.city,
                    postcode=request.postcode,
                )

            if bing_result:
                # Bing grounding returned results - apply them directly
                logger.info(f"Bing Grounding found results for: {request.name}")
                response.official_website = bing_result.get("official_website")
                response.uk_contact_phone = bing_result.get("uk_contact_phone")
                response.rooms_min = bing_result.get("rooms_min")
                response.rooms_max = bing_result.get("rooms_max")
                response.rooms_source_notes = bing_result.get("rooms_source_notes")
                response.confidence_score = bing_result.get("confidence", 0.0)
                response.website_source_url = "Bing Grounding"
                
                if bing_result.get("uk_contact_phone"):
                    response.phone_source_url = "Bing Grounding"

                # If we got a website, optionally do deep scraping for more data
                website_url = bing_result.get("official_website")
                if website_url and (not response.rooms_min or not response.uk_contact_phone):
                    logger.info(f"Bing found website {website_url}, deep scraping for missing data...")
                    await self._deep_scrape_and_extract(request, response, website_url)
                
                # Determine status
                if response.rooms_min and response.uk_contact_phone and response.official_website:
                    response.status = StatusEnum.SUCCESS
                elif response.rooms_min or response.uk_contact_phone or response.official_website:
                    response.status = StatusEnum.PARTIAL
                else:
                    response.status = StatusEnum.NOT_FOUND

                # Cache the result
                if use_cache and self.cache_service and self.cache_service.is_connected:
                    await self._cache_response(request.name, address_str, response)

                return response

            # Step 1b: Fallback to web search (SerpAPI/DuckDuckGo) if Bing grounding unavailable or failed
            logger.info(f"Falling back to web search for: {request.name}")
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
            
            website_url = official_result.get("url") or official_result.get("href")
            response.official_website = website_url
            
            # Note the source - could be Google Hotels, SerpAPI, or DuckDuckGo
            source = official_result.get("source", "Web search")
            response.website_source_url = source
            
            logger.info(f"Found website: {website_url} (source: {source})")
            
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
                
                # Try booking sites as fallback for room count
                if not response.rooms_min:
                    booking_result = await self._try_booking_sites(request)
                    if booking_result:
                        self._apply_booking_result(response, booking_result)
                        if response.rooms_min:
                            response.status = StatusEnum.PARTIAL
                            response.errors.append(f"Room count sourced from {booking_result.get('source', 'booking site')}")
                
                # Last resort: try planning portal for room count
                if not response.rooms_min:
                    planning_result = await self._try_planning_portal(request)
                    if planning_result:
                        self._apply_planning_result(response, planning_result)
                        if response.rooms_min:
                            response.errors.append(f"Room count sourced from planning portal")
            
            logger.info(f"Lookup complete for {request.name}: status={response.status}")
            
            # Cache the result if caching is enabled
            if use_cache and self.cache_service and self.cache_service.is_connected:
                await self._cache_response(request.name, address_str, response)
            
            return response
            
        except Exception as e:
            logger.error(f"Lookup error for {request.name}: {e}")
            response.status = StatusEnum.ERROR
            response.errors.append(str(e))
            return response
    
    async def _cache_response(self, hotel_name: str, address: Optional[str], response: HotelInfoResponse) -> None:
        """Cache a hotel lookup response"""
        try:
            # Convert response to dict for caching
            cache_data = {
                "search_name": response.search_name,
                "search_address": response.search_address,
                "official_website": response.official_website,
                "uk_contact_phone": response.uk_contact_phone,
                "rooms_min": response.rooms_min,
                "rooms_max": response.rooms_max,
                "rooms_source_notes": response.rooms_source_notes,
                "website_source_url": response.website_source_url,
                "phone_source_url": response.phone_source_url,
                "status": response.status.value if response.status else "partial",
                "last_checked": response.last_checked.isoformat() if response.last_checked else None,
                "confidence_score": response.confidence_score,
                "errors": response.errors
            }
            await self.cache_service.set_hotel_lookup(hotel_name, address, cache_data)
        except Exception as e:
            logger.warning(f"Failed to cache result for {hotel_name}: {e}")
    
    async def lookup_batch(self, requests: List[HotelSearchRequest], delay_seconds: float = 1.5, max_concurrent: int = 5) -> List[HotelInfoResponse]:
        """
        Process multiple hotel lookups with controlled parallelism.
        
        Args:
            requests: List of hotel search requests
            delay_seconds: Delay between starting each batch of concurrent requests
            max_concurrent: Maximum number of hotels to process in parallel (default 5)
        """
        import asyncio
        
        results = [None] * len(requests)  # Pre-allocate to maintain order
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(index: int, request: HotelSearchRequest):
            async with semaphore:
                logger.info(f"Starting lookup {index+1}/{len(requests)}: {request.name}")
                result = await self.lookup_hotel(request)
                results[index] = result
                # Small delay after completing to spread out API calls
                await asyncio.sleep(delay_seconds)
                return result
        
        # Create tasks for all requests
        tasks = [
            process_with_semaphore(i, req) 
            for i, req in enumerate(requests)
        ]
        
        # Run all tasks concurrently (semaphore limits actual parallelism)
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any None results (from exceptions)
        for i, result in enumerate(results):
            if result is None:
                results[i] = HotelInfoResponse(
                    search_name=requests[i].name,
                    search_address=self._build_address(requests[i]),
                    status=StatusEnum.ERROR,
                    errors=["Lookup failed unexpectedly"]
                )
        
        successful = sum(1 for r in results if r.status == StatusEnum.SUCCESS)
        partial = sum(1 for r in results if r.status == StatusEnum.PARTIAL)
        logger.info(f"Batch complete: {successful} success, {partial} partial, {len(results)-successful-partial} failed")
        
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
    
    async def _try_planning_portal(self, request: HotelSearchRequest) -> Optional[dict]:
        """
        Last resort: Try to find room count from local council planning portal.
        Planning applications often contain room counts in their descriptions.
        """
        try:
            logger.info(f"Trying planning portal for room count: {request.name}")
            result = await self.planning_service.search_planning_portal(
                hotel_name=request.name,
                address=request.address,
                city=request.city,
                postcode=request.postcode
            )
            if result and result.get("room_count"):
                return result
        except Exception as e:
            logger.warning(f"Planning portal lookup failed: {e}")
        return None
    
    def _apply_planning_result(self, response: HotelInfoResponse, planning_result: dict):
        """Apply results from planning portal to the response"""
        if planning_result.get("room_count"):
            response.rooms_min = planning_result["room_count"]
            response.rooms_max = planning_result["room_count"]
            notes = planning_result.get("notes", "Found in planning application")
            response.rooms_source_notes = f"Planning portal: {notes}"
            if planning_result.get("source_url"):
                response.rooms_source_notes += f" ({planning_result['source_url']})"

    async def _deep_scrape_and_extract(
        self, request: HotelSearchRequest, response: HotelInfoResponse, website_url: str
    ) -> None:
        """
        Deep scrape a hotel website and use AI to extract missing information.
        Used to supplement Bing grounding results when some data is missing.
        """
        try:
            scrape_result = await self.scraper_service.deep_scrape_hotel(website_url)
            
            if not scrape_result["success"]:
                response.errors.append(f"Deep scrape failed for {website_url}")
                return
            
            # Check for domain parking
            parking_check = self.scraper_service.detect_domain_parking(
                html=scrape_result.get("raw_html", ""),
                text_content=scrape_result["text_content"]
            )
            if parking_check["is_parked"]:
                response.errors.append("Website appears to be parked - data may be stale")
                return
            
            # Use AI to extract additional information
            if self.ai_service.is_configured:
                extraction = await self.ai_service.extract_hotel_info(
                    hotel_name=request.name,
                    website_content=scrape_result["text_content"],
                    phone_candidates=scrape_result["phone_numbers"],
                    room_candidates=scrape_result["room_mentions"]
                )
                
                # Fill in missing data from extraction
                if not response.rooms_min and extraction.get("rooms_min"):
                    response.rooms_min = extraction["rooms_min"]
                    response.rooms_max = extraction.get("rooms_max", response.rooms_min)
                    response.rooms_source_notes = extraction.get("rooms_source_notes", "Extracted from hotel website")
                
                if not response.uk_contact_phone and extraction.get("uk_phone"):
                    response.uk_contact_phone = extraction["uk_phone"]
                    response.phone_source_url = website_url
                
                # Update confidence if extraction had higher confidence
                extraction_confidence = extraction.get("confidence", 0.0)
                if extraction_confidence > (response.confidence_score or 0.0):
                    response.confidence_score = extraction_confidence

        except Exception as e:
            logger.warning(f"Deep scrape/extract failed for {website_url}: {e}")
            response.errors.append(f"Deep scrape error: {str(e)}")

