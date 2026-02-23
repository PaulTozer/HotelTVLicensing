"""
Bing Grounding Service - Uses Azure AI Foundry Agent with Bing Grounding
to search for hotel information, replacing SerpAPI/DuckDuckGo.

The HotelTVSearch agent uses Bing grounding to find:
- Official hotel websites
- UK contact phone numbers  
- Room counts
"""

import json
import logging
import asyncio
from typing import Optional, Dict, Any, List

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import BingGroundingTool, AgentThreadCreationOptions, ThreadMessageOptions
from azure.identity import DefaultAzureCredential

from config import (
    AZURE_AI_PROJECT_ENDPOINT,
    AZURE_AI_MODEL_DEPLOYMENT,
    BING_CONNECTION_NAME,
)

logger = logging.getLogger(__name__)

# Agent instructions for the HotelTVSearch agent
SEARCH_AGENT_INSTRUCTIONS = """You are a hotel information research assistant called HotelTVSearch. 
Your job is to search the web to find accurate information about UK hotels.

When given a hotel name (and optionally an address/city), you must search for and return:

1. **Official Website**: The hotel's own website URL (NOT booking sites like booking.com, expedia, hotels.com, tripadvisor, agoda, kayak, trivago)
2. **UK Contact Phone**: The hotel's direct UK phone number (starting with +44, 01, 02, 03, or 0800)
3. **Room Count**: The total number of guest rooms/bedrooms

IMPORTANT RULES:
- Search specifically using Bing to find the hotel
- Always prioritise the hotel's OWN official website over aggregator/booking sites
- For phone numbers, prefer landline (01, 02, 03) over mobile (07)
- For room counts, look for phrases like "X rooms", "X bedrooms", "X guest rooms"
- If you find a range (e.g., "150-200 rooms"), provide both min and max
- Only include information you are confident about
- If you cannot find a piece of information, set it to null

You MUST respond with ONLY valid JSON in this exact format (no markdown, no explanation, just JSON):
{
    "official_website": "<URL or null>",
    "uk_contact_phone": "<phone number or null>",
    "rooms_min": <number or null>,
    "rooms_max": <number or null>,
    "rooms_source_notes": "<brief note about where you found room info, or null>",
    "hotel_name_found": "<the exact hotel name as found online>",
    "address_found": "<the address if found, or null>",
    "confidence": <0.0 to 1.0>,
    "search_sources": ["<list of URLs used as sources>"]
}
"""


class BingGroundingService:
    """
    Service that uses an Azure AI Foundry agent with Bing grounding
    to search for hotel information.
    """

    def __init__(
        self,
        project_endpoint: Optional[str] = None,
        model_deployment: Optional[str] = None,
        bing_connection_name: Optional[str] = None,
    ):
        self.project_endpoint = project_endpoint or AZURE_AI_PROJECT_ENDPOINT
        self.model_deployment = model_deployment or AZURE_AI_MODEL_DEPLOYMENT
        self.bing_connection_name = bing_connection_name or BING_CONNECTION_NAME

        self._client: Optional[AIProjectClient] = None
        self._agent = None
        self._initialized = False

    @property
    def is_configured(self) -> bool:
        """Check if the service has the required configuration"""
        return bool(self.project_endpoint and self.bing_connection_name)

    def _get_client(self) -> AIProjectClient:
        """Get or create the AIProjectClient (lazy init)"""
        if self._client is None:
            credential = DefaultAzureCredential()
            self._client = AIProjectClient(
                endpoint=self.project_endpoint,
                credential=credential,
            )
            logger.info(f"Connected to AI Foundry project: {self.project_endpoint}")
        return self._client

    def _ensure_agent(self) -> None:
        """Create the HotelTVSearch agent if not already created"""
        if self._agent is not None:
            return

        client = self._get_client()

        # Get the Bing connection
        bing_connection = client.connections.get(self.bing_connection_name)
        logger.info(f"Using Bing connection: {bing_connection.id}")

        # Create the Bing grounding tool
        bing_tool = BingGroundingTool(
            connection_id=bing_connection.id,
            market="en-GB",  # UK market for UK hotel searches
            count=10,  # Number of search results to ground from
        )

        # Create the agent
        self._agent = client.agents.create_agent(
            model=self.model_deployment,
            name="HotelTVSearch",
            description="Searches for hotel information using Bing grounding",
            instructions=SEARCH_AGENT_INSTRUCTIONS,
            tools=bing_tool.definitions,
        )

        logger.info(f"Created HotelTVSearch agent: {self._agent.id}")
        self._initialized = True

    def _build_search_prompt(
        self,
        name: str,
        address: Optional[str] = None,
        city: Optional[str] = None,
        postcode: Optional[str] = None,
    ) -> str:
        """Build the search prompt for the agent"""
        parts = [f'Find information about the hotel: "{name}"']

        location_parts = []
        if address:
            location_parts.append(address)
        if city:
            location_parts.append(city)
        if postcode:
            location_parts.append(postcode)

        if location_parts:
            parts.append(f"Location: {', '.join(location_parts)}")

        parts.append(
            "\nSearch for the hotel's official website, UK phone number, and room count. "
            "Return ONLY the JSON response as specified in your instructions."
        )

        return "\n".join(parts)

    def search_hotel(
        self,
        name: str,
        address: Optional[str] = None,
        city: Optional[str] = None,
        postcode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search for hotel information using the Bing grounding agent.
        
        This is a synchronous method that creates a thread, sends a message,
        and waits for the agent to process it.
        
        Returns a dict with hotel information or empty dict on failure.
        """
        if not self.is_configured:
            logger.warning("BingGroundingService not configured")
            return {}

        try:
            self._ensure_agent()
            client = self._get_client()

            # Build the search prompt
            prompt = self._build_search_prompt(name, address, city, postcode)
            logger.info(f"Searching with Bing grounding agent for: {name}")

            # Create thread and process run in one call
            run = client.agents.create_thread_and_process_run(
                agent_id=self._agent.id,
                thread=AgentThreadCreationOptions(
                    messages=[
                        ThreadMessageOptions(
                            role="user",
                            content=prompt,
                        )
                    ]
                ),
            )

            if run.status != "completed":
                logger.error(f"Agent run failed with status: {run.status}")
                if hasattr(run, "last_error") and run.last_error:
                    logger.error(f"Agent error: {run.last_error}")
                return {}

            # Get the response messages
            messages = client.agents.messages.list(thread_id=run.thread_id)
            
            # Find the assistant's response
            for msg in messages:
                if msg.role == "assistant":
                    # Extract text content
                    for content_block in msg.content:
                        if hasattr(content_block, "text"):
                            response_text = content_block.text.value
                            logger.debug(f"Agent response: {response_text[:500]}")
                            
                            # Parse the JSON response
                            result = self._parse_agent_response(response_text)
                            if result:
                                result["source"] = "Bing Grounding"
                                return result

            logger.warning(f"No valid response from agent for: {name}")
            return {}

        except Exception as e:
            logger.error(f"Bing grounding search failed for {name}: {e}")
            return {}

    async def search_hotel_async(
        self,
        name: str,
        address: Optional[str] = None,
        city: Optional[str] = None,
        postcode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async wrapper around search_hotel using thread executor"""
        return await asyncio.to_thread(
            self.search_hotel, name, address, city, postcode
        )

    def _parse_agent_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Parse the agent's JSON response, handling markdown code blocks"""
        if not response_text:
            return None

        # Strip markdown code block if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            result = json.loads(text)
            
            # Validate the response has expected fields
            if not isinstance(result, dict):
                logger.warning("Agent response is not a JSON object")
                return None

            # Normalize the result
            return {
                "official_website": result.get("official_website"),
                "uk_contact_phone": result.get("uk_contact_phone"),
                "rooms_min": result.get("rooms_min"),
                "rooms_max": result.get("rooms_max"),
                "rooms_source_notes": result.get("rooms_source_notes"),
                "hotel_name_found": result.get("hotel_name_found"),
                "address_found": result.get("address_found"),
                "confidence": result.get("confidence", 0.0),
                "search_sources": result.get("search_sources", []),
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse agent response as JSON: {e}")
            logger.debug(f"Raw response: {text[:500]}")

            # Try to extract JSON from within the text
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                json_str = text[start:end]
                result = json.loads(json_str)
                return {
                    "official_website": result.get("official_website"),
                    "uk_contact_phone": result.get("uk_contact_phone"),
                    "rooms_min": result.get("rooms_min"),
                    "rooms_max": result.get("rooms_max"),
                    "rooms_source_notes": result.get("rooms_source_notes"),
                    "hotel_name_found": result.get("hotel_name_found"),
                    "address_found": result.get("address_found"),
                    "confidence": result.get("confidence", 0.0),
                    "search_sources": result.get("search_sources", []),
                }
            except (ValueError, json.JSONDecodeError):
                logger.error("Could not extract JSON from agent response")
                return None

    def cleanup(self) -> None:
        """Clean up the agent and client"""
        if self._agent and self._client:
            try:
                self._client.agents.delete_agent(self._agent.id)
                logger.info(f"Deleted HotelTVSearch agent: {self._agent.id}")
            except Exception as e:
                logger.warning(f"Failed to delete agent: {e}")
        
        if self._client:
            self._client.close()
            self._client = None
        
        self._agent = None
        self._initialized = False

    async def cleanup_async(self) -> None:
        """Async cleanup wrapper"""
        await asyncio.to_thread(self.cleanup)


# Module-level singleton
_bing_service: Optional[BingGroundingService] = None


def get_bing_grounding_service() -> BingGroundingService:
    """Get or create the singleton BingGroundingService instance"""
    global _bing_service
    if _bing_service is None:
        _bing_service = BingGroundingService()
    return _bing_service
