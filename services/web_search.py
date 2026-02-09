"""Web search service to find hotel websites with fallback providers"""

import logging
import asyncio
import httpx
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import RatelimitException, DuckDuckGoSearchException
from tenacity import retry, stop_after_attempt, wait_exponential

from config import SEARCH_MAX_RETRIES, SERPAPI_API_KEY

logger = logging.getLogger(__name__)

# Try to import SerpAPI
try:
    from serpapi import GoogleSearch
    SERPAPI_AVAILABLE = bool(SERPAPI_API_KEY)
    if SERPAPI_AVAILABLE:
        logger.info("SerpAPI configured and available")
except ImportError:
    SERPAPI_AVAILABLE = False
    logger.warning("SerpAPI not installed, will use DuckDuckGo")


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
        
        # FIRST: Try Google Hotels API via SerpAPI - best for official website discovery
        # Google Hotels often has the official hotel website directly in the property listing
        if SERPAPI_AVAILABLE:
            try:
                google_hotels_result = self._search_google_hotels_for_website(name, effective_city)
                if google_hotels_result:
                    logger.info(f"Google Hotels found official website for '{name}'")
                    return google_hotels_result
            except Exception as e:
                logger.warning(f"Google Hotels API error: {e}")
        
        # Try SerpAPI Google Search next (most reliable general search)
        if SERPAPI_AVAILABLE:
            try:
                results = self._search_serpapi(query)
                if results:
                    ranked_results = self._rank_results(results, name)
                    logger.info(f"SerpAPI returned {len(ranked_results)} results for '{name}'")
                    if ranked_results:
                        return ranked_results
            except Exception as e:
                logger.warning(f"SerpAPI error: {e}")
        
        # Fallback to DuckDuckGo (unless recently rate limited)
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
    
    def _search_serpapi(self, query: str) -> List[Dict[str, Any]]:
        """
        Search using SerpAPI (Google Search API).
        Most reliable search provider with consistent results.
        """
        try:
            params = {
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "engine": "google",
                "num": 10,
                "gl": "uk",  # UK results
                "hl": "en",  # English
            }
            
            search = GoogleSearch(params)
            results = search.get_dict()
            
            organic_results = results.get("organic_results", [])
            logger.info(f"SerpAPI returned {len(organic_results)} organic results")
            
            formatted_results = []
            for result in organic_results:
                formatted_results.append({
                    "href": result.get("link", ""),
                    "title": result.get("title", ""),
                    "body": result.get("snippet", "")
                })
            
            return formatted_results
            
        except Exception as e:
            logger.warning(f"SerpAPI search failed: {e}")
            return []
    
    def _search_google_hotels_for_website(self, hotel_name: str, city: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Search Google Hotels via SerpAPI to find the official hotel website.
        Google Hotels often has the official website URL directly in the property listing,
        which is more reliable than searching for it via web search.
        
        Returns a list with single result containing the official website, or None if not found.
        """
        from datetime import datetime, timedelta
        
        try:
            query = hotel_name
            if city:
                query = f"{hotel_name} {city}"
            
            # Google Hotels API requires check-in/check-out dates
            # Use tomorrow and day after for the search (dates don't matter for finding the hotel)
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            day_after = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
            
            params = {
                "engine": "google_hotels",
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "gl": "uk",
                "hl": "en",
                "currency": "GBP",
                "check_in_date": tomorrow,
                "check_out_date": day_after,
                "adults": 2,
            }
            
            logger.info(f"Searching Google Hotels for official website: {query} (dates: {tomorrow} to {day_after})")
            search = GoogleSearch(params)
            results = search.get_dict()
            
            # Check for errors in response
            if "error" in results:
                logger.warning(f"Google Hotels API error: {results.get('error')}")
                return None
            
            # Log some metadata to help debug
            search_info = results.get("search_information", {})
            logger.info(f"Google Hotels search info: {search_info}")
            
            # Check if this is a single property details response (exact hotel name match)
            # When the query matches exactly, Google returns property details at root level
            hotels_results_state = search_info.get("hotels_results_state", "")
            
            if hotels_results_state == "Showing results for property details":
                # Single property match - data is at root level, not in properties array
                logger.info(f"Google Hotels returned single property details for exact match")
                
                # Extract official website from root level
                official_website = None
                
                # Check 'link' field at root level
                link = results.get("link")
                if link:
                    aggregator_domains = ['booking.com', 'expedia.', 'hotels.com', 'tripadvisor.', 
                                          'google.com', 'agoda.', 'kayak.', 'trivago.', 'priceline.']
                    is_aggregator = any(agg in link.lower() for agg in aggregator_domains)
                    if not is_aggregator:
                        official_website = link
                        logger.info(f"Found official website from single property result: {official_website}")
                
                # Check 'website' field at root level
                if not official_website:
                    website = results.get("website")
                    if website:
                        official_website = website
                        logger.info(f"Found official website from website field: {official_website}")
                
                if official_website:
                    hotel_name_from_results = results.get("name", hotel_name)
                    return [{
                        "href": official_website,
                        "url": official_website,
                        "title": hotel_name_from_results,
                        "body": results.get("description", ""),
                        "is_aggregator": False,
                        "source": "Google Hotels"
                    }]
            
            # Look for properties in the results - could also be under 'brands' 
            properties = results.get("properties", [])
            brands = results.get("brands", [])
            
            # Sometimes hotels show up in brands instead of properties
            if not properties and brands:
                logger.info(f"No properties but found {len(brands)} brands - using brands")
                properties = brands
            
            if not properties:
                # Log available keys to understand response structure
                logger.info(f"No properties found. Response keys: {list(results.keys())}")
                return None
            
            logger.info(f"Google Hotels returned {len(properties)} properties")
            
            # Find the best matching property
            hotel_name_lower = hotel_name.lower()
            # Remove "the" prefix and "hotel" suffix for better matching
            clean_name = hotel_name_lower
            if clean_name.startswith("the "):
                clean_name = clean_name[4:]
            if clean_name.endswith(" hotel"):
                clean_name = clean_name[:-6]
            clean_name = clean_name.strip()
            
            best_match = None
            
            for i, prop in enumerate(properties):
                prop_name = prop.get("name", "").lower()
                prop_clean = prop_name
                if prop_clean.startswith("the "):
                    prop_clean = prop_clean[4:]
                if prop_clean.endswith(" hotel"):
                    prop_clean = prop_clean[:-6]
                prop_clean = prop_clean.strip()
                
                logger.debug(f"Google Hotels property {i}: {prop.get('name')} - keys: {list(prop.keys())}")
                
                # Check for name match
                if clean_name in prop_clean or prop_clean in clean_name:
                    best_match = prop
                    logger.info(f"Google Hotels exact match: {prop.get('name')}")
                    break
                # Check for partial match
                name_words = clean_name.split()
                if len(name_words) >= 1:
                    if all(word in prop_clean for word in name_words):
                        best_match = prop
                        logger.info(f"Google Hotels partial match: {prop.get('name')}")
                        break
            
            if not best_match and properties:
                # Use first result if it contains key words from hotel name
                first_prop = properties[0]
                first_name = first_prop.get("name", "").lower()
                first_clean = first_name
                if first_clean.startswith("the "):
                    first_clean = first_clean[4:]
                    
                # Check if any significant word matches
                significant_words = [w for w in clean_name.split() if len(w) > 3]
                if any(word in first_clean for word in significant_words):
                    best_match = first_prop
                    logger.info(f"Using first Google Hotels result (word match): {first_prop.get('name')}")
            
            if best_match:
                logger.info(f"Google Hotels matched: {best_match.get('name')} - available keys: {list(best_match.keys())}")
                
                # Extract official website URL
                # Google Hotels provides this in various fields
                official_website = None
                
                # Check 'link' field - often the official website
                link = best_match.get("link")
                if link:
                    logger.info(f"Google Hotels link field: {link}")
                    # Filter out booking aggregators
                    aggregator_domains = ['booking.com', 'expedia.', 'hotels.com', 'tripadvisor.', 
                                          'google.com', 'agoda.', 'kayak.', 'trivago.', 'priceline.']
                    is_aggregator = any(agg in link.lower() for agg in aggregator_domains)
                    if not is_aggregator:
                        official_website = link
                        logger.info(f"Found official website from Google Hotels link: {official_website}")
                    else:
                        logger.info(f"Link is aggregator, skipping: {link}")
                
                # Check 'website' field if no link
                if not official_website:
                    website = best_match.get("website")
                    if website:
                        official_website = website
                        logger.info(f"Found official website from Google Hotels website field: {official_website}")
                
                # Check 'hotel_link' field
                if not official_website:
                    hotel_link = best_match.get("hotel_link")
                    if hotel_link:
                        logger.info(f"Google Hotels hotel_link field: {hotel_link}")
                        aggregator_domains = ['booking.com', 'expedia.', 'hotels.com', 'tripadvisor.', 
                                              'google.com', 'agoda.', 'kayak.', 'trivago.', 'priceline.']
                        is_aggregator = any(agg in hotel_link.lower() for agg in aggregator_domains)
                        if not is_aggregator:
                            official_website = hotel_link
                            logger.info(f"Found official website from Google Hotels hotel_link: {official_website}")
                
                # Check 'serpapi_property_details_link' - this can be followed for more details
                if not official_website:
                    details_link = best_match.get("serpapi_property_details_link")
                    if details_link:
                        logger.info(f"No direct website found, but serpapi_property_details_link available: {details_link}")
                
                if official_website:
                    # Return as a search result
                    return [{
                        "href": official_website,
                        "url": official_website,
                        "title": best_match.get("name", hotel_name),
                        "body": best_match.get("description", ""),
                        "is_aggregator": False,
                        "source": "Google Hotels"
                    }]
                else:
                    logger.info(f"Google Hotels matched {best_match.get('name')} but no official website URL found")
            else:
                logger.info(f"No matching property found in Google Hotels for '{hotel_name}'")
            
            return None
            
        except Exception as e:
            logger.warning(f"Google Hotels website search failed: {e}")
            return None
    
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
