"""Web search service to find hotel websites with fallback providers"""

import logging
import asyncio
import httpx
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import RatelimitException, DuckDuckGoSearchException
from tenacity import retry, stop_after_attempt, wait_exponential

from config import SEARCH_MAX_RETRIES, AZURE_BING_SEARCH_KEY, AZURE_BING_SEARCH_ENDPOINT, USE_AZURE_BING_SEARCH

logger = logging.getLogger(__name__)


class WebSearchService:
    """Service for searching the web to find hotel websites"""
    
    # Allowed domain TLDs for UK, European, and US hotel websites
    ALLOWED_TLDS = {
        # UK
        '.co.uk', '.uk', '.org.uk',
        # US
        '.com', '.us', '.net', '.org',
        # Europe
        '.eu', '.de', '.fr', '.es', '.it', '.nl', '.be', '.at', '.ch',
        '.ie', '.pt', '.pl', '.se', '.no', '.dk', '.fi', '.gr',
    }
    
    # Blocked domains (non-UK/EU/US or irrelevant)
    BLOCKED_DOMAINS = [
        '.cn', '.zh', '.jp', '.kr', '.ru', '.br', '.in', '.za',
        '.au', '.nz', '.mx', '.ar', '.cl', '.co', '.tw', '.hk',
        '.sg', '.my', '.th', '.vn', '.id', '.ph',
        'zhihu.com', 'baidu.com', 'weibo.com', 'qq.com',
        'wikipedia.org', 'facebook.com', 'twitter.com', 'instagram.com',
        'youtube.com', 'linkedin.com', 'pinterest.com', 'reddit.com',
    ]
    
    def __init__(self):
        self.ddgs = DDGS()
        self.http_client = httpx.Client(timeout=30.0)
        self._ddg_rate_limited = False
        self._ddg_rate_limit_until = 0
        self._use_bing_api = USE_AZURE_BING_SEARCH
        if self._use_bing_api:
            logger.info("Azure Bing Search API configured as primary search provider")
    
    def _build_search_query(self, name: str, address: Optional[str] = None, 
                            city: Optional[str] = None, postcode: Optional[str] = None) -> str:
        """Build an effective search query for finding hotel website"""
        parts = [f'"{name}"', "hotel", "UK"]
        
        if city:
            parts.append(city)
        elif address:
            # Try to extract city from address
            parts.append(address.split(",")[-1].strip() if "," in address else address)
        
        if postcode:
            parts.append(postcode)
        
        parts.append("official website")
        
        return " ".join(parts)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def search_hotel_website(self, name: str, address: Optional[str] = None,
                             city: Optional[str] = None, postcode: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for a hotel's official website with fallback providers.
        
        Priority order:
        1. Azure Bing Search API (if configured) - most reliable, paid service
        2. DuckDuckGo (free, but rate limited)
        3. Bing scraping fallback
        4. Direct URL construction
        
        Returns list of search results with title, url, and description
        """
        query = self._build_search_query(name, address, city, postcode)
        logger.info(f"Searching for: {query}")
        
        # Extract city from address if not provided
        effective_city = city
        if not effective_city and address:
            # Common UK cities to check
            uk_cities = ['london', 'manchester', 'birmingham', 'edinburgh', 'glasgow', 
                         'liverpool', 'bristol', 'leeds', 'sheffield', 'newcastle',
                         'brighton', 'bath', 'oxford', 'cambridge', 'york', 'cardiff']
            addr_lower = address.lower()
            for c in uk_cities:
                if c in addr_lower:
                    effective_city = c
                    break
        
        results = []
        
        # Try Azure Bing Search API first (if configured)
        if self._use_bing_api:
            try:
                results = self._search_azure_bing_api(query)
                if results:
                    ranked_results = self._rank_results(results, name)
                    logger.info(f"Azure Bing API returned {len(ranked_results)} results")
                    if ranked_results:
                        return ranked_results
            except Exception as e:
                logger.warning(f"Azure Bing Search API error: {e}, falling back to DuckDuckGo")
        
        # Try DuckDuckGo (unless recently rate limited)
        import time
        if not self._ddg_rate_limited or time.time() > self._ddg_rate_limit_until:
            try:
                results = list(self.ddgs.text(query, max_results=10))
                logger.info(f"DuckDuckGo returned {len(results)} raw results")
                self._ddg_rate_limited = False  # Reset on success
                
                if results:
                    ranked_results = self._rank_results(results, name)
                    logger.info(f"Found {len(ranked_results)} results for '{name}' after filtering")
                    if ranked_results:
                        return ranked_results
                        
            except RatelimitException as e:
                logger.warning(f"DuckDuckGo rate limit: {e}")
                self._ddg_rate_limited = True
                self._ddg_rate_limit_until = time.time() + 60  # Back off for 60 seconds
                
            except DuckDuckGoSearchException as e:
                logger.warning(f"DuckDuckGo search error: {e}")
                
            except Exception as e:
                logger.warning(f"DuckDuckGo unexpected error: {e}")
        else:
            logger.info("Skipping DuckDuckGo (rate limited), using fallback")
        
        # Fallback 1: Try Bing scraping
        if not results:
            try:
                results = self._search_bing_fallback(query)
                if results:
                    ranked_results = self._rank_results(results, name)
                    logger.info(f"Bing fallback returned {len(ranked_results)} results")
                    if ranked_results:
                        return ranked_results
            except Exception as e:
                logger.warning(f"Bing fallback error: {e}")
        
        # Fallback 2: Try to construct likely URLs directly
        logger.info(f"Trying direct URL construction for '{name}' with city='{effective_city}'")
        return self._construct_likely_urls(name, effective_city)
    
    def _search_bing_fallback(self, query: str) -> List[Dict[str, Any]]:
        """
        Fallback search using Bing's public search page scraping.
        Less reliable but useful when DuckDuckGo is rate limited.
        """
        import re
        from bs4 import BeautifulSoup
        
        try:
            encoded_query = quote_plus(query)
            url = f"https://www.bing.com/search?q={encoded_query}&count=10"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-GB,en;q=0.9',
            }
            
            response = self.http_client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            results = []
            
            # Parse Bing search results
            for item in soup.select('li.b_algo'):
                title_elem = item.select_one('h2 a')
                desc_elem = item.select_one('.b_caption p')
                
                if title_elem:
                    href = title_elem.get('href', '')
                    title = title_elem.get_text(strip=True)
                    desc = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    if href and href.startswith('http'):
                        results.append({
                            'href': href,
                            'title': title,
                            'body': desc
                        })
            
            logger.info(f"Bing scraping returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.warning(f"Bing scraping failed: {e}")
            return []
    
    def _search_azure_bing_api(self, query: str) -> List[Dict[str, Any]]:
        """
        Search using Azure Bing Search API (paid, reliable service).
        
        This is the preferred search method when configured as it has:
        - Higher rate limits
        - More reliable results
        - Better quality/relevance
        """
        try:
            headers = {
                'Ocp-Apim-Subscription-Key': AZURE_BING_SEARCH_KEY,
            }
            
            params = {
                'q': query,
                'count': 10,
                'mkt': 'en-GB',  # UK market for better local results
                'safeSearch': 'Moderate',
            }
            
            response = self.http_client.get(
                AZURE_BING_SEARCH_ENDPOINT,
                headers=headers,
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            # Parse web pages from response
            web_pages = data.get('webPages', {}).get('value', [])
            
            for item in web_pages:
                results.append({
                    'href': item.get('url', ''),
                    'title': item.get('name', ''),
                    'body': item.get('snippet', '')
                })
            
            logger.info(f"Azure Bing API returned {len(results)} results")
            return results
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("Azure Bing Search API: Invalid subscription key")
            elif e.response.status_code == 403:
                logger.error("Azure Bing Search API: Access forbidden - check subscription")
            elif e.response.status_code == 429:
                logger.warning("Azure Bing Search API: Rate limited")
            else:
                logger.error(f"Azure Bing Search API HTTP error: {e}")
            raise
            
        except Exception as e:
            logger.error(f"Azure Bing Search API error: {e}")
            raise
    
    def _rank_results(self, results: List[Dict], hotel_name: str) -> List[Dict[str, Any]]:
        """Rank search results by likelihood of being the official website"""
        scored_results = []
        hotel_name_lower = hotel_name.lower()
        
        # Keywords that indicate official sites
        official_indicators = ["book", "rooms", "reservations", "stay", "accommodation"]
        
        # Keywords that indicate aggregator/review sites (lower priority)
        aggregator_domains = [
            "booking.com", "tripadvisor", "expedia", "hotels.com", 
            "trivago", "kayak", "agoda", "priceline", "hotelscombined",
            "laterooms", "lastminute", "travelodge", "premierinn"
        ]
        
        for result in results:
            url = result.get("href", "") or result.get("url", "")
            title = result.get("title", "").lower()
            body = result.get("body", "") or result.get("description", "")
            
            url_lower = url.lower()
            
            # Skip blocked domains (non-UK/EU/US)
            if self._is_blocked_domain(url_lower):
                logger.debug(f"Skipping blocked domain: {url}")
                continue
            
            score = 0
            
            # Check if hotel name appears in URL (strong signal)
            name_parts = hotel_name_lower.replace("the ", "").replace("hotel", "").split()
            
            for part in name_parts:
                if len(part) > 2 and part in url_lower:
                    score += 20
            
            # Check if it's an aggregator site (negative signal)
            is_aggregator = any(agg in url_lower for agg in aggregator_domains)
            if is_aggregator:
                score -= 50
            
            # Official indicators in title/description
            for indicator in official_indicators:
                if indicator in title or indicator in body.lower():
                    score += 5
            
            # Prefer .co.uk and .com domains
            if ".co.uk" in url_lower:
                score += 15
            elif ".uk" in url_lower:
                score += 12
            elif ".com" in url_lower and not is_aggregator:
                score += 8
            elif any(tld in url_lower for tld in ['.eu', '.de', '.fr', '.es', '.it', '.ie']):
                score += 5  # European domains for hotel chains
            
            # Check for "official" in title
            if "official" in title:
                score += 15
            
            scored_results.append({
                "url": url,
                "title": result.get("title", ""),
                "description": body,
                "score": score,
                "is_aggregator": is_aggregator
            })
        
        # Sort by score descending
        scored_results.sort(key=lambda x: x["score"], reverse=True)
        
        # Only return results with positive scores (filtered results)
        return [r for r in scored_results if r["score"] > -20]
    
    def _is_blocked_domain(self, url: str) -> bool:
        """Check if a URL is from a blocked domain (non-UK/EU/US)"""
        url_lower = url.lower()
        
        # Explicitly blocked domains (known non-relevant sites)
        explicit_blocks = [
            'zhihu.com', 'baidu.com', 'weibo.com', 'qq.com', 'sina.com',
            'taobao.com', 'alibaba.com', 'jd.com', '163.com', 'sohu.com',
            'wikipedia.org', 'facebook.com', 'twitter.com', 'instagram.com',
            'youtube.com', 'linkedin.com', 'pinterest.com', 'reddit.com',
            'tiktok.com', 'vk.com', 'yandex.ru',
        ]
        
        # Check explicit blocks
        for blocked in explicit_blocks:
            if blocked in url_lower:
                logger.debug(f"Blocked explicit domain: {url}")
                return True
        
        # Blocked TLDs (non-UK/EU/US countries)
        blocked_tlds = [
            '.cn', '.ru', '.jp', '.kr', '.br', '.in', '.za',
            '.au', '.nz', '.mx', '.ar', '.cl', '.tw', '.hk',
            '.sg', '.my', '.th', '.vn', '.id', '.ph', '.pk',
        ]
        
        # Check if URL ends with a blocked TLD
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url_lower)
            domain = parsed.netloc
            
            for tld in blocked_tlds:
                if domain.endswith(tld):
                    logger.debug(f"Blocked TLD domain: {url}")
                    return True
                    
        except Exception:
            pass
        
        return False
    
    def _construct_likely_urls(self, name: str, city: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Construct likely hotel website URLs based on common naming patterns
        """
        import re
        
        # Clean the hotel name for URL construction
        clean_name = re.sub(r'[^\w\s-]', '', name.lower())
        clean_name = re.sub(r'\s+', '', clean_name)  # Remove spaces (e.g., "edgbastonpalacehotel")
        clean_name_dash = re.sub(r'\s+', '-', re.sub(r'[^\w\s-]', '', name.lower()))  # With dashes
        
        # Keep version with "the" for brands that use it
        clean_name_with_the = "the" + clean_name.replace("the", "")
        
        # Remove common prefixes/suffixes for cleaner URLs  
        clean_name_no_prefix = clean_name
        clean_name_dash_no_prefix = clean_name_dash
        for remove in ['the', 'hotel', 'inn', 'lodge']:
            clean_name_no_prefix = clean_name_no_prefix.replace(remove, '')
            clean_name_dash_no_prefix = clean_name_dash_no_prefix.replace(f'{remove}-', '').replace(f'-{remove}', '')
        
        clean_name_no_prefix = clean_name_no_prefix.strip('-')
        clean_name_dash_no_prefix = clean_name_dash_no_prefix.strip('-')
        
        # Also create version without the city name (e.g., "Brighton Marina House Hotel" -> "marinahouse")
        # Hotels often don't include the city name in their domain
        clean_name_no_city = clean_name
        clean_name_no_city_no_prefix = clean_name_no_prefix
        
        clean_city = re.sub(r'[^\w]', '', city.lower()) if city else ''
        
        if clean_city:
            clean_name_no_city = clean_name.replace(clean_city, '')
            clean_name_no_city_no_prefix = clean_name_no_prefix.replace(clean_city, '')
        
        candidates = []
        
        # Try common URL patterns - FULL NAME FIRST (most specific), then variations
        url_patterns = []
        
        # Full name patterns (e.g., edgbastonpalacehotel.co.uk)
        url_patterns.extend([
            f"https://www.{clean_name}.co.uk",
            f"http://www.{clean_name}.co.uk",  # Some hotels use HTTP
            f"https://www.{clean_name}.com",
            f"http://www.{clean_name}.com",
            f"https://www.{clean_name_dash}.co.uk",
            f"http://www.{clean_name_dash}.co.uk",
        ])
        
        # City-specific variants (like thesavoylondon.com)
        if clean_city:
            url_patterns.extend([
                f"https://www.{clean_name_with_the}{clean_city}.com",
                f"https://www.{clean_name_no_prefix}{clean_city}.com",
                f"https://www.{clean_name_with_the}{clean_city}.co.uk",
                f"https://www.{clean_name_no_prefix}{clean_city}.co.uk",
                f"https://www.the{clean_name_no_prefix}{clean_city}.com",
                f"https://www.{clean_name_no_prefix}{clean_city}hotel.com",
            ])
        
        # IMPORTANT: Patterns WITHOUT city name in domain (e.g., "Brighton Marina House Hotel" -> marinahousehotel.com)
        # Many hotels don't include the city in their domain name
        if clean_name_no_city_no_prefix and clean_name_no_city_no_prefix != clean_name_no_prefix:
            url_patterns.extend([
                f"https://www.{clean_name_no_city_no_prefix}hotel.com",
                f"https://{clean_name_no_city_no_prefix}hotel.com",
                f"https://www.{clean_name_no_city_no_prefix}hotel.co.uk",
                f"https://{clean_name_no_city_no_prefix}hotel.co.uk",
                f"https://www.{clean_name_no_city_no_prefix}.com",
                f"https://{clean_name_no_city_no_prefix}.com",
                f"https://www.{clean_name_no_city_no_prefix}.co.uk",
                f"https://{clean_name_no_city_no_prefix}.co.uk",
            ])
        
        # Standard patterns (without full name)
        url_patterns.extend([
            f"https://www.{clean_name_no_prefix}hotel.co.uk",
            f"http://www.{clean_name_no_prefix}hotel.co.uk",
            f"https://www.{clean_name_dash_no_prefix}hotel.co.uk", 
            f"https://www.{clean_name_no_prefix}.co.uk",
            f"http://www.{clean_name_no_prefix}.co.uk",
            f"https://www.{clean_name_dash_no_prefix}.co.uk",
            f"https://www.the{clean_name_no_prefix}.co.uk",
            f"https://www.the{clean_name_no_prefix}hotel.co.uk",
            f"https://www.{clean_name_no_prefix}hotel.com",
            f"https://www.{clean_name_no_prefix}.com",
            f"https://www.the{clean_name_no_prefix}.com",
        ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_patterns = []
        for p in url_patterns:
            if p not in seen:
                seen.add(p)
                unique_patterns.append(p)
        url_patterns = unique_patterns
        
        logger.info(f"Trying {len(url_patterns)} URL patterns for '{name}'")
        
        # Test each URL
        for url in url_patterns:
            try:
                response = self.http_client.head(url, follow_redirects=True, timeout=5.0)
                if response.status_code == 200:
                    candidates.append({
                        "url": str(response.url),  # Use final URL after redirects
                        "title": f"Likely official website for {name}",
                        "description": f"Direct URL test successful",
                        "score": 50,
                        "is_aggregator": False
                    })
                    logger.info(f"Found working URL: {response.url}")
                    break  # Found one, that's enough
            except Exception:
                continue
        
        return candidates
    
    def search_booking_aggregator(self, name: str, city: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for hotel on booking aggregator sites when official website fails.
        These sites often have room counts and reliable information.
        """
        import re
        
        # Clean hotel name for URL patterns
        clean_name = re.sub(r'[^\w\s]', '', name.lower())
        clean_name = re.sub(r'\s+', '', clean_name)  # No spaces
        clean_name_no_prefix = clean_name
        for remove in ['the', 'hotel', 'inn', 'lodge']:
            clean_name_no_prefix = clean_name_no_prefix.replace(remove, '')
        
        clean_city = re.sub(r'[^\w]', '', city.lower()) if city else ''
        
        candidates = []
        
        # Try city-specific booking aggregator patterns
        # Pattern: hotelname.hotels-cityname.net
        if clean_city:
            aggregator_patterns = [
                f"https://{clean_name_no_prefix}.hotels-{clean_city}.net/en/",
                f"https://{clean_name}.hotels-{clean_city}.net/en/",
                f"https://the{clean_name_no_prefix}.hotels-{clean_city}.net/en/",
            ]
            
            for url in aggregator_patterns:
                try:
                    logger.info(f"Trying booking aggregator: {url}")
                    response = self.http_client.get(url, follow_redirects=True, timeout=10.0)
                    if response.status_code == 200:
                        # Verify it's actually a hotel page, not a 404 soft redirect
                        content = response.text.lower()
                        if 'hotel' in content and ('room' in content or 'check-in' in content):
                            candidates.append({
                                "url": str(response.url),
                                "title": f"Booking page for {name}",
                                "description": "Found on booking aggregator",
                                "score": 40,
                                "is_aggregator": True
                            })
                            logger.info(f"Found booking aggregator: {response.url}")
                            return candidates
                except Exception as e:
                    logger.debug(f"Aggregator URL failed: {url} - {e}")
                    continue
        
        # If no direct URL match, try a search specifically for booking sites
        try:
            query = f'"{name}" {city or ""} hotel rooms booking'
            results = list(self.ddgs.text(query, max_results=5))
            
            for r in results:
                url = r.get("href", "") or r.get("url", "")
                if any(agg in url.lower() for agg in ['hotels-', 'booking.com', 'hotels.com']):
                    candidates.append({
                        "url": url,
                        "title": r.get("title", ""),
                        "description": r.get("body", ""),
                        "score": 35,
                        "is_aggregator": True
                    })
                    logger.info(f"Found booking site via search: {url}")
                    
            if candidates:
                return candidates[:1]  # Return best match
                
        except Exception as e:
            logger.warning(f"Booking aggregator search error: {e}")
        
        return candidates
    
    def search_hotel_contact(self, name: str, website: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search specifically for hotel contact information"""
        if website:
            query = f'site:{website} contact phone'
        else:
            query = f'"{name}" hotel UK contact phone number'
        
        try:
            results = list(self.ddgs.text(query, max_results=5))
            return [{"url": r.get("href", ""), "title": r.get("title", ""), 
                    "description": r.get("body", "")} for r in results]
        except Exception as e:
            logger.error(f"Contact search error: {e}")
            return []
    
    def search_hotel_rooms(self, name: str, website: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search specifically for room count information"""
        if website:
            query = f'site:{website} rooms bedrooms accommodation'
        else:
            query = f'"{name}" hotel UK "rooms" OR "bedrooms" number'
        
        try:
            results = list(self.ddgs.text(query, max_results=5))
            return [{"url": r.get("href", ""), "title": r.get("title", ""), 
                    "description": r.get("body", "")} for r in results]
        except Exception as e:
            logger.error(f"Rooms search error: {e}")
            return []
