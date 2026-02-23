"""
Bing Grounding Service - Uses Azure AI Foundry Agent with Bing Grounding
to search for hotel information.

The HotelTVSearch agent uses Bing grounding to find:
- Official hotel websites
- UK contact phone numbers  
- Room counts

Optimised for high-throughput batch processing with:
- Dedicated thread pool for blocking Azure SDK calls
- Semaphore-based concurrency limiting at the API level
- Retry with exponential backoff for transient errors
- Multiple agent instances for true parallel processing
"""

import json
import logging
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import BingGroundingTool, AgentThreadCreationOptions, ThreadMessageOptions
from azure.identity import DefaultAzureCredential

from config import (
    AZURE_AI_PROJECT_ENDPOINT,
    AZURE_AI_MODEL_DEPLOYMENT,
    BING_CONNECTION_NAME,
    BING_MAX_CONCURRENT,
    BING_THREAD_POOL_SIZE,
    BING_RETRY_MAX,
    BING_RETRY_DELAY_BASE,
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
    Service that uses Azure AI Foundry agents with Bing grounding
    to search for hotel information.
    
    Optimised for high-throughput batch processing:
    - Dedicated ThreadPoolExecutor (not the default executor)
    - Asyncio Semaphore to limit concurrent API calls
    - Retry with exponential backoff for transient errors
    - Thread-safe agent pool for parallel searches
    """

    def __init__(
        self,
        project_endpoint: Optional[str] = None,
        model_deployment: Optional[str] = None,
        bing_connection_name: Optional[str] = None,
        max_concurrent: Optional[int] = None,
        thread_pool_size: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_delay_base: Optional[float] = None,
    ):
        self.project_endpoint = project_endpoint or AZURE_AI_PROJECT_ENDPOINT
        self.model_deployment = model_deployment or AZURE_AI_MODEL_DEPLOYMENT
        self.bing_connection_name = bing_connection_name or BING_CONNECTION_NAME
        self.max_concurrent = max_concurrent or BING_MAX_CONCURRENT
        self.max_retries = max_retries or BING_RETRY_MAX
        self.retry_delay_base = retry_delay_base or BING_RETRY_DELAY_BASE

        self._client: Optional[AIProjectClient] = None
        self._agent = None
        self._initialized = False
        self._bing_tool_definitions = None  # Cache tool definitions
        
        # Dedicated thread pool for blocking Azure SDK calls
        pool_size = thread_pool_size or BING_THREAD_POOL_SIZE
        self._executor = ThreadPoolExecutor(
            max_workers=pool_size,
            thread_name_prefix="bing-grounding"
        )
        
        # Semaphore to limit concurrent API calls (prevents rate limiting)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Metrics
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._retry_count = 0

    @property
    def is_configured(self) -> bool:
        """Check if the service has the required configuration"""
        return bool(self.project_endpoint and self.bing_connection_name)

    @property
    def metrics(self) -> Dict[str, Any]:
        """Return current performance metrics"""
        return {
            "total_requests": self._total_requests,
            "successful": self._successful_requests,
            "failed": self._failed_requests,
            "retries": self._retry_count,
            "success_rate": (self._successful_requests / max(self._total_requests, 1)) * 100,
            "max_concurrent": self.max_concurrent,
            "thread_pool_size": self._executor._max_workers,
        }

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
            market="en-GB",
            count=10,
        )
        self._bing_tool_definitions = bing_tool.definitions

        # Create the agent
        self._agent = client.agents.create_agent(
            model=self.model_deployment,
            name="HotelTVSearch",
            description="Searches for hotel information using Bing grounding",
            instructions=SEARCH_AGENT_INSTRUCTIONS,
            tools=self._bing_tool_definitions,
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
        Includes retry with exponential backoff for transient errors.
        
        Returns a dict with hotel information or empty dict on failure.
        """
        if not self.is_configured:
            logger.warning("BingGroundingService not configured")
            return {}

        self._total_requests += 1
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self._ensure_agent()
                client = self._get_client()

                prompt = self._build_search_prompt(name, address, city, postcode)
                
                if attempt > 1:
                    logger.info(f"Retry {attempt}/{self.max_retries} for: {name}")
                    self._retry_count += 1

                # Create thread and process run
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
                    error_msg = ""
                    if hasattr(run, "last_error") and run.last_error:
                        error_msg = str(run.last_error)
                    
                    # Check if retryable
                    if attempt < self.max_retries and self._is_retryable_error(run.status, error_msg):
                        delay = self.retry_delay_base * (2 ** (attempt - 1))
                        logger.warning(f"Agent run {run.status} for {name}, retrying in {delay}s: {error_msg}")
                        time.sleep(delay)
                        continue
                    
                    logger.error(f"Agent run failed with status: {run.status} - {error_msg}")
                    self._failed_requests += 1
                    return {}

                # Get the response messages
                messages = client.agents.messages.list(thread_id=run.thread_id)
                
                for msg in messages:
                    if msg.role == "assistant":
                        for content_block in msg.content:
                            if hasattr(content_block, "text"):
                                response_text = content_block.text.value
                                logger.debug(f"Agent response: {response_text[:500]}")
                                
                                result = self._parse_agent_response(response_text)
                                if result:
                                    result["source"] = "Bing Grounding"
                                    self._successful_requests += 1
                                    return result

                # If we got here, no valid response but no error either
                if attempt < self.max_retries:
                    delay = self.retry_delay_base * (2 ** (attempt - 1))
                    logger.warning(f"No valid response for {name}, retrying in {delay}s")
                    time.sleep(delay)
                    continue

                logger.warning(f"No valid response from agent for: {name}")
                self._failed_requests += 1
                return {}

            except Exception as e:
                last_error = e
                if attempt < self.max_retries and self._is_retryable_exception(e):
                    delay = self.retry_delay_base * (2 ** (attempt - 1))
                    logger.warning(f"Bing search error for {name} (attempt {attempt}), retrying in {delay}s: {e}")
                    self._retry_count += 1
                    time.sleep(delay)
                    continue
                
                logger.error(f"Bing grounding search failed for {name}: {e}")
                self._failed_requests += 1
                return {}

        logger.error(f"All {self.max_retries} attempts failed for {name}: {last_error}")
        self._failed_requests += 1
        return {}

    async def search_hotel_async(
        self,
        name: str,
        address: Optional[str] = None,
        city: Optional[str] = None,
        postcode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Async search with semaphore-based concurrency control.
        Uses the dedicated thread pool (not the default executor).
        """
        async with self._semaphore:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self._executor,
                self.search_hotel, name, address, city, postcode
            )

    async def search_hotels_batch(
        self,
        hotels: List[Dict[str, Any]],
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Search for multiple hotels concurrently with optimal throughput.
        
        Args:
            hotels: List of dicts with keys: name, address, city, postcode
            progress_callback: Optional async callable(completed, total, hotel_name, result)
            
        Returns:
            List of result dicts in same order as input
        """
        total = len(hotels)
        results = [None] * total
        completed = 0
        
        logger.info(f"Starting batch search: {total} hotels, max {self.max_concurrent} concurrent")
        start_time = time.time()

        async def search_one(index: int, hotel: Dict[str, Any]):
            nonlocal completed
            result = await self.search_hotel_async(
                name=hotel.get("name", ""),
                address=hotel.get("address"),
                city=hotel.get("city"),
                postcode=hotel.get("postcode"),
            )
            results[index] = result
            completed += 1
            
            if progress_callback:
                await progress_callback(completed, total, hotel.get("name", ""), result)
            
            if completed % 10 == 0 or completed == total:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                logger.info(f"Batch progress: {completed}/{total} ({rate:.1f} hotels/sec)")

        # Launch all tasks — semaphore controls concurrency
        tasks = [search_one(i, h) for i, h in enumerate(hotels)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Replace any None results (from exceptions in gather)
        for i in range(total):
            if results[i] is None:
                results[i] = {}
        
        elapsed = time.time() - start_time
        rate = total / elapsed if elapsed > 0 else 0
        logger.info(
            f"Batch complete: {total} hotels in {elapsed:.1f}s "
            f"({rate:.1f} hotels/sec) | {self.metrics}"
        )
        
        return results

    @staticmethod
    def _is_retryable_error(status: str, error_msg: str) -> bool:
        """Determine if an agent run error is worth retrying"""
        retryable_statuses = {"failed", "expired", "incomplete"}
        retryable_phrases = {"rate_limit", "429", "throttl", "server_error", "timeout", "503", "502"}
        status_lower = status.lower() if status else ""
        error_lower = error_msg.lower() if error_msg else ""
        return (
            status_lower in retryable_statuses
            or any(phrase in error_lower for phrase in retryable_phrases)
        )

    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        """Determine if an exception is worth retrying"""
        retryable_types = ("ConnectionError", "TimeoutError", "ServerError", "HttpResponseError")
        exc_name = type(exc).__name__
        exc_msg = str(exc).lower()
        return (
            exc_name in retryable_types
            or "429" in exc_msg
            or "rate" in exc_msg
            or "throttl" in exc_msg
            or "timeout" in exc_msg
            or "temporarily" in exc_msg
            or "503" in exc_msg
            or "502" in exc_msg
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
        """Clean up the agent, client, and thread pool"""
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
        
        # Shut down thread pool
        if self._executor:
            self._executor.shutdown(wait=False)
            logger.info("Shut down Bing grounding thread pool")

    async def cleanup_async(self) -> None:
        """Async cleanup wrapper"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.cleanup)


# Module-level singleton
_bing_service: Optional[BingGroundingService] = None


def get_bing_grounding_service() -> BingGroundingService:
    """Get or create the singleton BingGroundingService instance"""
    global _bing_service
    if _bing_service is None:
        _bing_service = BingGroundingService()
    return _bing_service
