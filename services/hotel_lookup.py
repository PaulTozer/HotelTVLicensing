"""Main hotel lookup orchestration service"""

import logging
import time
from typing import Optional, List, Callable, Awaitable
from datetime import datetime

from models import HotelSearchRequest, HotelInfoResponse, StatusEnum
from .web_scraper import WebScraperService
from .ai_extractor import AIExtractorService
from .planning_portal import PlanningPortalService
from .cache_service import CacheService
from .bing_grounding_service import BingGroundingService
from config import BATCH_MAX_CONCURRENT

logger = logging.getLogger(__name__)


class HotelLookupService:
    """Orchestrates the full hotel information lookup process"""
    
    def __init__(self, cache_service: Optional[CacheService] = None, 
                 bing_grounding_service: Optional[BingGroundingService] = None):
        self.bing_service = bing_grounding_service
        self.scraper_service = WebScraperService()
        self.ai_service = AIExtractorService()
        self.planning_service = PlanningPortalService()
        self.cache_service = cache_service
    
    async def lookup_hotel(self, request: HotelSearchRequest, use_cache: bool = True, skip_deep_scrape: bool = False) -> HotelInfoResponse:
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
                if not skip_deep_scrape and website_url and (not response.rooms_min or not response.uk_contact_phone):
                    logger.info(f"Bing found website {website_url}, deep scraping for missing data...")
                    await self._deep_scrape_and_extract(request, response, website_url)
                elif skip_deep_scrape and (not response.rooms_min or not response.uk_contact_phone):
                    logger.info(f"Skipping deep scrape for {request.name} (fast mode)")
                
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

            # Bing Grounding unavailable or returned no results
            if skip_deep_scrape:
                logger.info(f"Skipping fallback for {request.name} (fast mode, Bing returned no results)")
                response.status = StatusEnum.NOT_FOUND
                response.errors.append("Fast mode: Bing Grounding returned no results, skipped fallback")
                return response

            # Without Bing results, try booking sites and planning portal as last resort
            logger.info(f"Bing Grounding returned no results for: {request.name}")
            
            booking_result = await self._try_booking_sites(request)
            if booking_result:
                self._apply_booking_result(response, booking_result)
                response.status = StatusEnum.PARTIAL
                response.errors.append(f"Data sourced from {booking_result.get('source', 'booking site')} as fallback")
            
            if not response.rooms_min:
                planning_result = await self._try_planning_portal(request)
                if planning_result:
                    self._apply_planning_result(response, planning_result)
                    response.errors.append("Room count sourced from planning portal")
            
            # Determine final status
            if response.rooms_min and response.uk_contact_phone and response.official_website:
                response.status = StatusEnum.SUCCESS
            elif response.rooms_min or response.uk_contact_phone or response.official_website:
                response.status = StatusEnum.PARTIAL
            else:
                response.status = StatusEnum.NOT_FOUND
                response.errors.append("No information found from any source")
            
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
    
    async def lookup_batch(
        self,
        requests: List[HotelSearchRequest],
        delay_seconds: float = 0.0,
        max_concurrent: int = None,
        progress_callback: Optional[Callable] = None,
        skip_deep_scrape: bool = False,
    ) -> List[HotelInfoResponse]:
        """
        Process multiple hotel lookups with high-throughput parallelism.
        
        Concurrency is primarily controlled by the BingGroundingService semaphore.
        An additional semaphore here limits overall resource usage for the full
        lookup pipeline (scraping, AI extraction, etc.).
        
        Args:
            requests: List of hotel search requests
            delay_seconds: Optional delay between starts (0 = no delay, semaphore controls flow)
            max_concurrent: Max concurrent full lookups (default from config)
            progress_callback: Optional async callable(completed, total, hotel_name, status)
            skip_deep_scrape: If True, skip deep scraping for faster results (Bing-only)
        """
        import asyncio
        
        max_concurrent = max_concurrent or BATCH_MAX_CONCURRENT
        total = len(requests)
        results = [None] * total
        completed = 0
        semaphore = asyncio.Semaphore(max_concurrent)
        start_time = time.time()
        
        logger.info(
            f"Starting batch lookup: {total} hotels, max {max_concurrent} concurrent"
            f"{', fast mode (no deep scrape)' if skip_deep_scrape else ''}"
        )
        
        async def process_one(index: int, request: HotelSearchRequest):
            nonlocal completed
            async with semaphore:
                try:
                    logger.info(f"[{index+1}/{total}] Starting: {request.name}")
                    result = await self.lookup_hotel(request, skip_deep_scrape=skip_deep_scrape)
                    results[index] = result
                except Exception as e:
                    logger.error(f"[{index+1}/{total}] Failed: {request.name}: {e}")
                    results[index] = HotelInfoResponse(
                        search_name=request.name,
                        search_address=self._build_address(request),
                        status=StatusEnum.ERROR,
                        errors=[str(e)]
                    )
                finally:
                    completed += 1
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    
                    status = results[index].status.value if results[index] else "error"
                    
                    if completed % 10 == 0 or completed == total:
                        logger.info(
                            f"Batch progress: {completed}/{total} "
                            f"({rate:.1f}/sec, elapsed {elapsed:.0f}s)"
                        )
                    
                    if progress_callback:
                        try:
                            await progress_callback(completed, total, request.name, status)
                        except Exception:
                            pass
        
        # Launch all tasks — semaphore controls actual concurrency
        tasks = [process_one(i, req) for i, req in enumerate(requests)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any None results
        for i, result in enumerate(results):
            if result is None:
                results[i] = HotelInfoResponse(
                    search_name=requests[i].name,
                    search_address=self._build_address(requests[i]),
                    status=StatusEnum.ERROR,
                    errors=["Lookup failed unexpectedly"]
                )
        
        elapsed = time.time() - start_time
        successful = sum(1 for r in results if r.status == StatusEnum.SUCCESS)
        partial = sum(1 for r in results if r.status == StatusEnum.PARTIAL)
        failed = total - successful - partial
        rate = total / elapsed if elapsed > 0 else 0
        
        logger.info(
            f"Batch complete: {total} hotels in {elapsed:.1f}s ({rate:.1f}/sec) "
            f"| {successful} success, {partial} partial, {failed} failed"
        )
        
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

