"""AI-powered extraction service using OpenAI/Azure OpenAI"""

import json
import logging
from typing import Optional, Dict, Any, List
from openai import OpenAI, AzureOpenAI

from config import (
    OPENAI_API_KEY, 
    AZURE_OPENAI_ENDPOINT, 
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_DEPLOYMENT,
    USE_AZURE_OPENAI
)

logger = logging.getLogger(__name__)


class AIExtractorService:
    """Service for AI-powered data extraction from scraped content"""
    
    EXTRACTION_PROMPT = """You are an expert at extracting hotel information from website content.

Given the following scraped website content for a hotel, extract the following information:

1. **Room Count**: The total number of rooms/bedrooms in the hotel
   - Look for phrases like "X rooms", "X bedrooms", "X guest rooms", "accommodation for X"
   - If a range is mentioned (e.g., "150-200 rooms"), provide both min and max
   - If only one number is found, use it for both min and max
   
2. **UK Contact Phone Number**: The main contact/reservations phone number
   - Must be a UK number (starting with +44, 0, or UK area codes)
   - Prefer landline numbers (01, 02, 03) over mobile (07)
   - Prefer direct hotel numbers over chain booking lines

3. **Notes about the room count source**: Brief description of where/how you found the room count

IMPORTANT:
- Only extract information you can clearly find in the content
- If information is not available, return null
- Be conservative with confidence scores
- Room counts should be realistic (typically 10-500 for most hotels, up to 2000 for very large ones)

Respond in valid JSON format with this exact structure:
{
    "rooms_min": <number or null>,
    "rooms_max": <number or null>,
    "uk_phone": "<phone number or null>",
    "rooms_source_notes": "<brief description of where you found room info, or null>",
    "phone_source_notes": "<brief description of where you found phone, or null>",
    "confidence": <0.0 to 1.0>,
    "reasoning": "<brief explanation of your extraction>"
}"""

    def __init__(self):
        self.client = None
        self.model = "gpt-4o-mini"  # Cost-effective and capable
        
        if USE_AZURE_OPENAI:
            self.client = AzureOpenAI(
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_key=AZURE_OPENAI_API_KEY,
                api_version="2024-02-15-preview"
            )
            self.model = AZURE_OPENAI_DEPLOYMENT
            logger.info("Using Azure OpenAI")
        elif OPENAI_API_KEY:
            self.client = OpenAI(api_key=OPENAI_API_KEY)
            logger.info("Using OpenAI")
        else:
            logger.warning("No AI provider configured!")
    
    @property
    def is_configured(self) -> bool:
        """Check if AI service is properly configured"""
        return self.client is not None
    
    def get_provider_name(self) -> str:
        """Get the name of the configured AI provider"""
        if USE_AZURE_OPENAI:
            return "Azure OpenAI"
        elif OPENAI_API_KEY:
            return "OpenAI"
        return "None"
    
    async def extract_hotel_info(
        self, 
        hotel_name: str,
        website_content: str,
        phone_candidates: List[Dict[str, str]],
        room_candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Use AI to extract structured hotel information from scraped content
        
        Args:
            hotel_name: Name of the hotel being searched
            website_content: Scraped text content from website
            phone_candidates: Pre-extracted phone numbers from scraper
            room_candidates: Pre-extracted room mentions from scraper
        
        Returns:
            Dictionary with extracted information
        """
        if not self.is_configured:
            logger.error("AI service not configured")
            return self._fallback_extraction(phone_candidates, room_candidates)
        
        # Build context for AI
        context = f"""Hotel Name: {hotel_name}

Pre-extracted Phone Numbers Found:
{json.dumps(phone_candidates, indent=2) if phone_candidates else "None found"}

Pre-extracted Room Count Mentions:
{json.dumps(room_candidates, indent=2) if room_candidates else "None found"}

Website Content:
{website_content[:12000]}"""  # Limit content length for API

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.EXTRACTION_PROMPT},
                    {"role": "user", "content": context}
                ],
                max_completion_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            
            logger.info(f"AI extraction complete for {hotel_name}: confidence={result.get('confidence')}")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}")
            return self._fallback_extraction(phone_candidates, room_candidates)
        except Exception as e:
            logger.error(f"AI extraction error: {e}")
            return self._fallback_extraction(phone_candidates, room_candidates)
    
    def _fallback_extraction(
        self,
        phone_candidates: List[Dict[str, str]],
        room_candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Fallback extraction when AI is unavailable
        Uses simple heuristics on pre-extracted data
        """
        result = {
            "rooms_min": None,
            "rooms_max": None,
            "uk_phone": None,
            "rooms_source_notes": None,
            "phone_source_notes": "Fallback extraction (AI unavailable)",
            "confidence": 0.3,
            "reasoning": "Used fallback extraction due to AI unavailability"
        }
        
        # Get best phone (prefer landlines)
        if phone_candidates:
            landlines = [p for p in phone_candidates if p.get("type") == "landline"]
            if landlines:
                result["uk_phone"] = landlines[0]["formatted"]
            else:
                result["uk_phone"] = phone_candidates[0]["formatted"]
        
        # Get room count (use most confident or most frequent)
        if room_candidates:
            # Sort by confidence
            sorted_rooms = sorted(room_candidates, key=lambda x: x.get("confidence", 0), reverse=True)
            if sorted_rooms:
                result["rooms_min"] = sorted_rooms[0]["count"]
                result["rooms_max"] = sorted_rooms[0]["count"]
                result["rooms_source_notes"] = sorted_rooms[0].get("context", "")[:200]
        
        return result
    
    async def verify_website_is_correct(
        self, 
        hotel_name: str, 
        hotel_address: Optional[str],
        website_content: str
    ) -> Dict[str, Any]:
        """
        Use AI to verify if the website content matches the hotel we're looking for
        """
        if not self.is_configured:
            return {"is_match": True, "confidence": 0.5, "reason": "AI unavailable for verification"}
        
        prompt = f"""Determine if this website content is for the correct hotel.

Hotel we're looking for:
- Name: {hotel_name}
- Address: {hotel_address or 'Not provided'}

Website content excerpt:
{website_content[:3000]}

Respond in JSON:
{{
    "is_match": <true/false>,
    "confidence": <0.0 to 1.0>,
    "found_name": "<hotel name found on website>",
    "found_location": "<location mentioned on website>",
    "reason": "<brief explanation>"
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You verify if website content matches a specific hotel."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=200,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            logger.error(f"Website verification error: {e}")
            return {"is_match": True, "confidence": 0.5, "reason": f"Verification failed: {e}"}
