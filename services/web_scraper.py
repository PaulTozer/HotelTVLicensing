"""Web scraping service to extract content from hotel websites"""

import logging
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse, quote_plus
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
import phonenumbers

from config import USER_AGENT, SCRAPE_TIMEOUT_SECONDS
from .playwright_service import get_playwright_service, PLAYWRIGHT_AVAILABLE

logger = logging.getLogger(__name__)

# Domain parking indicators - websites that have been abandoned
DOMAIN_PARKING_INDICATORS = [
    'domain parking', 'parked domain', 'this domain', 'domain for sale',
    'buy this domain', 'fasthosts', 'godaddy parking', 'sedoparking',
    'hugedomains', 'dan.com', 'undeveloped.com', 'afternic',
    'domain is for sale', 'website coming soon', 'under construction',
    'parked free', 'domain expired', 'this site is not available',
    'get your own domain', 'register this domain', 'domain name for sale',
    'this website is for sale', 'buy now for', 'make offer'
]

# Domain parking indicators - websites that have been abandoned
DOMAIN_PARKING_INDICATORS = [
    'domain parking', 'parked domain', 'this domain', 'domain for sale',
    'buy this domain', 'fasthosts', 'godaddy parking', 'sedoparking',
    'hugedomains', 'dan.com', 'undeveloped.com', 'afternic',
    'domain is for sale', 'website coming soon', 'under construction',
    'parked free', 'domain expired', 'this site is not available',
    'get your own domain', 'register this domain'
]


class WebScraperService:
    """Service for scraping hotel websites"""
    
    # Large hotel chains that would never have small room counts
    CHAIN_PATTERNS = [
        # IHG brands
        r'\bholiday\s*inn\b', r'\bcrowne\s*plaza\b', r'\bintercontinental\b', r'\bihg\b',
        r'\bkimpton\b', r'\bhotel\s*indigo\b', r'\beven\s*hotels?\b', r'\bstaybridge\b',
        # Marriott brands
        r'\bmarriott\b', r'\bcourtyard\b', r'\bresidence\s*inn\b', r'\bfairfield\b',
        r'\bspringhill\b', r'\btowneplace\b', r'\bsheraton\b', r'\bwestin\b',
        r'\bw\s+hotel\b', r'\baloft\b', r'\belement\b', r'\bmoxie\b', r'\britz.carlton\b',
        # Hilton brands
        r'\bhilton\b', r'\bdoubletree\b', r'\bhampton\b', r'\bembassy\s*suites\b',
        r'\bhomewood\s*suites\b', r'\bconrad\b', r'\bwaldorf\b', r'\bcurio\b', r'\btapestry\b',
        # UK chains
        r'\bpremier\s*inn\b', r'\btravelodge\b', r'\bjurys\s*inn\b', r'\bmaldron\b',
        # Accor brands
        r'\bnovotel\b', r'\bibis\b', r'\bmercure\b', r'\bsofitel\b', r'\bpullman\b',
        r'\baccor\b', r'\bmgallery\b',
        # Wyndham brands
        r'\bwyndham\b', r'\bramada\b', r'\bdays\s*inn\b', r'\bsuper\s*8\b', r'\bwingate\b',
        # Radisson brands
        r'\bradisson\b', r'\bpark\s*inn\b', r'\bcountry\s*inn\b',
        # Best Western
        r'\bbest\s*western\b',
        # Hyatt brands
        r'\bhyatt\b', r'\bandaz\b', r'\bthompson\b',
        # Choice brands
        r'\bclarion\b', r'\bquality\s*inn\b', r'\bcomfort\s*inn\b', r'\bsleep\s*inn\b',
    ]
    
    def __init__(self):
        self.timeout = httpx.Timeout(SCRAPE_TIMEOUT_SECONDS)
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }
        # Compile chain patterns for performance
        self._chain_regex = re.compile('|'.join(self.CHAIN_PATTERNS), re.IGNORECASE)
    
    def _is_chain_hotel(self, hotel_name: str) -> bool:
        """Check if hotel name matches a known chain brand"""
        return bool(self._chain_regex.search(hotel_name))
    
    def _get_min_room_threshold(self, hotel_name: str) -> int:
        """
        Get minimum room count threshold based on hotel type.
        Large chains would never have small room counts (typically 100-300+).
        Small independent hotels, pubs, and coaching inns may have 5-15 rooms.
        """
        if self._is_chain_hotel(hotel_name):
            logger.info(f"Detected chain hotel: {hotel_name} - using min threshold of 50 rooms")
            return 50  # Chains rarely have fewer than 50 rooms
        else:
            logger.info(f"Independent hotel: {hotel_name} - using min threshold of 5 rooms")
            return 5  # Small pubs, coaching inns, guest houses
    
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def fetch_page(self, url: str, use_playwright: bool = False) -> Optional[str]:
        """
        Fetch a webpage and return its HTML content.
        
        Args:
            url: The URL to fetch
            use_playwright: If True, use Playwright for JS rendering
            
        Returns:
            HTML content as string, or None if failed
        """
        # Use Playwright if requested and available
        if use_playwright and PLAYWRIGHT_AVAILABLE:
            return await self._fetch_with_playwright(url)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                # Ensure we get text, handling encoding properly
                return response.text
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching {url}")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error {e.response.status_code} for {url}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    async def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Fetch a page using Playwright for JavaScript rendering"""
        try:
            playwright = get_playwright_service()
            result = await playwright.fetch_rendered_page(url)
            
            if result["success"]:
                return result["html"]
            else:
                logger.warning(f"Playwright failed for {url}: {result.get('error')}")
                return None
        except Exception as e:
            logger.error(f"Playwright error for {url}: {e}")
            return None
    
    async def fetch_page_with_fallback(self, url: str) -> Dict[str, Any]:
        """
        Fetch a page, falling back to Playwright if content is minimal.
        
        Returns:
            Dict with 'html', 'text', 'used_playwright', 'success'
        """
        # First try regular HTTP
        html = await self.fetch_page(url, use_playwright=False)
        
        if not html:
            # HTTP failed, try Playwright if available
            if PLAYWRIGHT_AVAILABLE:
                logger.info(f"HTTP fetch failed, trying Playwright for {url}")
                html = await self.fetch_page(url, use_playwright=True)
                if html:
                    text = self.extract_text_content(html)
                    return {
                        "html": html,
                        "text": text,
                        "used_playwright": True,
                        "success": True
                    }
            return {
                "html": None,
                "text": None,
                "used_playwright": False,
                "success": False
            }
        
        # Check if content is minimal (might be JS-heavy site)
        text = self.extract_text_content(html)
        
        if PLAYWRIGHT_AVAILABLE:
            playwright = get_playwright_service()
            if await playwright.is_js_heavy_site(html, text):
                logger.info(f"Detected JS-heavy site, using Playwright for {url}")
                playwright_result = await playwright.fetch_rendered_page(url)
                
                if playwright_result["success"]:
                    playwright_text = playwright_result.get("text", "")
                    # Only use Playwright result if it has more content
                    if len(playwright_text) > len(text) * 1.5:
                        logger.info(f"Playwright returned more content ({len(playwright_text)} vs {len(text)} chars)")
                        return {
                            "html": playwright_result["html"],
                            "text": playwright_text,
                            "used_playwright": True,
                            "success": True
                        }
        
        return {
            "html": html,
            "text": text,
            "used_playwright": False,
            "success": True
        }
    
    def extract_text_content(self, html: str, max_length: int = 15000) -> str:
        """Extract readable text content from HTML"""
        soup = BeautifulSoup(html, 'lxml')
        
        # Remove script, style, and nav elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
            element.decompose()
        
        # Get text
        text = soup.get_text(separator=' ', strip=True)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "..."
        
        return text
    
    def detect_domain_parking(self, html: str, text_content: str) -> Dict[str, Any]:
        """Detect if a website is a domain parking page (business may have closed)"""
        text_lower = text_content.lower()
        html_lower = html.lower()
        
        # Check for parking indicators
        indicators_found = []
        for indicator in DOMAIN_PARKING_INDICATORS:
            if indicator in text_lower or indicator in html_lower:
                indicators_found.append(indicator)
        
        # Check for minimal content (parking pages are usually very short)
        word_count = len(text_content.split())
        is_minimal_content = word_count < 100
        
        # Check title for parking indicators
        soup = BeautifulSoup(html, 'lxml')
        title = soup.find('title')
        title_text = title.get_text().lower() if title else ''
        title_indicates_parking = any(ind in title_text for ind in ['parking', 'for sale', 'coming soon'])
        
        is_parked = len(indicators_found) > 0 or (is_minimal_content and title_indicates_parking)
        
        return {
            "is_parked": is_parked,
            "indicators_found": indicators_found,
            "word_count": word_count,
            "reason": "Domain appears to be parked - business may have closed" if is_parked else None
        }
    
    def extract_phone_numbers(self, html: str) -> List[Dict[str, str]]:
        """Extract UK phone numbers from HTML"""
        soup = BeautifulSoup(html, 'lxml')
        text = soup.get_text()
        
        phones = []
        
        # Common UK phone patterns
        patterns = [
            r'(?:\+44|0044|44)?[\s.-]?(?:0)?[\s.-]?(?:[1-9]\d{2,4})[\s.-]?\d{3,4}[\s.-]?\d{3,4}',
            r'(?:\+44|0)[\s.-]?\d{2,4}[\s.-]?\d{3,4}[\s.-]?\d{3,4}',
            r'0[1-9]\d{2,3}[\s.-]?\d{3}[\s.-]?\d{3,4}',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                # Clean up the number
                cleaned = re.sub(r'[\s.-]', '', match)
                
                # Try to parse as UK number
                try:
                    parsed = phonenumbers.parse(cleaned, "GB")
                    if phonenumbers.is_valid_number(parsed):
                        formatted = phonenumbers.format_number(
                            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                        )
                        if formatted not in [p["formatted"] for p in phones]:
                            phones.append({
                                "raw": match,
                                "formatted": formatted,
                                "type": self._get_phone_type(cleaned)
                            })
                except:
                    # Still include if it looks like a valid UK number
                    if cleaned.startswith(('01', '02', '03', '07', '08', '+44', '0044')):
                        if len(cleaned) >= 10 and cleaned not in [p["raw"] for p in phones]:
                            phones.append({
                                "raw": match.strip(),
                                "formatted": match.strip(),
                                "type": "unknown"
                            })
        
        return phones[:5]  # Return top 5 unique numbers
    
    def _get_phone_type(self, number: str) -> str:
        """Determine the type of UK phone number"""
        cleaned = number.replace('+44', '0').replace('0044', '0')
        if cleaned.startswith('01') or cleaned.startswith('02'):
            return "landline"
        elif cleaned.startswith('03'):
            return "non-geographic"
        elif cleaned.startswith('07'):
            return "mobile"
        elif cleaned.startswith('08'):
            return "freephone/special"
        return "unknown"
    
    def extract_room_mentions(self, html: str) -> List[Dict[str, Any]]:
        """Extract mentions of room counts from HTML"""
        soup = BeautifulSoup(html, 'lxml')
        text = soup.get_text()
        
        room_mentions = []
        
        # Patterns for room counts
        patterns = [
            (r'(\d+)\s*(?:luxury\s+)?(?:bed)?rooms?', 'rooms'),
            (r'(\d+)\s*(?:guest\s+)?(?:bed)?rooms?', 'guest rooms'),
            (r'(?:featuring|offers?|has|have|with)\s+(\d+)\s*(?:bed)?rooms?', 'feature'),
            (r'(\d+)\s*(?:en-suite\s+)?(?:bed)?rooms?', 'en-suite'),
            (r'total\s+(?:of\s+)?(\d+)\s*(?:bed)?rooms?', 'total'),
            (r'(\d+)\s*(?:individually\s+)?(?:designed\s+)?(?:bed)?rooms?', 'designed'),
            (r'(\d+)\s*suites?\s+(?:and|&)\s*(\d+)\s*(?:bed)?rooms?', 'suites_and_rooms'),
            (r'accommodation.*?(\d+)', 'accommodation'),
        ]
        
        for pattern, pattern_type in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    # Handle patterns with multiple groups
                    if pattern_type == 'suites_and_rooms' and len(match.groups()) >= 2:
                        suites = int(match.group(1))
                        rooms = int(match.group(2))
                        total = suites + rooms
                        context = text[max(0, match.start()-50):min(len(text), match.end()+50)]
                        room_mentions.append({
                            "count": total,
                            "type": pattern_type,
                            "context": context.strip(),
                            "confidence": 0.8
                        })
                    else:
                        count = int(match.group(1))
                        # Filter out unlikely room counts
                        if 1 <= count <= 2000:
                            context = text[max(0, match.start()-50):min(len(text), match.end()+50)]
                            room_mentions.append({
                                "count": count,
                                "type": pattern_type,
                                "context": context.strip(),
                                "confidence": 0.7
                            })
                except (ValueError, IndexError):
                    continue
        
        # Deduplicate and sort by count frequency
        seen_counts = {}
        for mention in room_mentions:
            count = mention["count"]
            if count not in seen_counts:
                seen_counts[count] = mention
            else:
                # Increase confidence if we see the same count multiple times
                seen_counts[count]["confidence"] = min(0.95, seen_counts[count]["confidence"] + 0.1)
        
        return list(seen_counts.values())
    
    def find_relevant_pages(self, html: str, base_url: str) -> List[str]:
        """Find links to relevant pages (about, rooms, contact, FAQ)"""
        soup = BeautifulSoup(html, 'lxml')
        
        # High priority keywords - pages that often have phone numbers or room info
        high_priority_keywords = ['contact', 'faq', 'frequently asked', 'enquir', 'call us', 'get in touch']
        
        # Medium priority keywords - pages with room/hotel info
        medium_priority_keywords = ['rooms', 'accommodation', 'about', 'hotel', 'overview', 'facilities']
        
        # Lower priority keywords
        low_priority_keywords = ['book', 'reservation', 'rates', 'prices', 'gallery']
        
        high_priority_urls = []
        medium_priority_urls = []
        low_priority_urls = []
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text().lower().strip()
            href_lower = href.lower()
            
            # Skip empty or anchor-only links
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            
            full_url = urljoin(base_url, href)
            
            # Avoid external links
            if not full_url.startswith('http') or urlparse(full_url).netloc != urlparse(base_url).netloc:
                continue
            
            # Check priority
            for keyword in high_priority_keywords:
                if keyword in href_lower or keyword in text:
                    if full_url not in high_priority_urls:
                        high_priority_urls.append(full_url)
                    break
            else:
                for keyword in medium_priority_keywords:
                    if keyword in href_lower or keyword in text:
                        if full_url not in medium_priority_urls:
                            medium_priority_urls.append(full_url)
                        break
                else:
                    for keyword in low_priority_keywords:
                        if keyword in href_lower or keyword in text:
                            if full_url not in low_priority_urls:
                                low_priority_urls.append(full_url)
                            break
        
        # Combine with priority order, removing duplicates
        all_urls = []
        for url in high_priority_urls + medium_priority_urls + low_priority_urls:
            if url not in all_urls:
                all_urls.append(url)
        
        return all_urls[:8]  # Return top 8 relevant pages (increased from 5)
    
    async def scrape_hotel_website(self, url: str, try_playwright_fallback: bool = True) -> Dict[str, Any]:
        """
        Scrape a hotel website for all relevant information.
        
        Uses Playwright as fallback for JavaScript-heavy sites.
        
        Args:
            url: The URL to scrape
            try_playwright_fallback: If True, try Playwright for JS-heavy sites
        
        Returns dict with:
        - text_content: Extracted text
        - phone_numbers: List of found phone numbers  
        - room_mentions: List of room count mentions
        - relevant_pages: List of URLs to relevant subpages
        - raw_html: Raw HTML content for domain parking detection
        - used_playwright: Whether Playwright was used
        """
        result = {
            "url": url,
            "text_content": "",
            "phone_numbers": [],
            "room_mentions": [],
            "relevant_pages": [],
            "raw_html": "",
            "used_playwright": False,
            "success": False
        }
        
        if try_playwright_fallback and PLAYWRIGHT_AVAILABLE:
            # Use the smart fallback method
            fetch_result = await self.fetch_page_with_fallback(url)
            
            if not fetch_result["success"]:
                return result
            
            html = fetch_result["html"]
            result["used_playwright"] = fetch_result["used_playwright"]
            
            if result["used_playwright"]:
                logger.info(f"Used Playwright for JavaScript rendering: {url}")
        else:
            # Standard HTTP fetch
            html = await self.fetch_page(url)
            if not html:
                return result
        
        result["raw_html"] = html
        result["text_content"] = self.extract_text_content(html)
        result["phone_numbers"] = self.extract_phone_numbers(html)
        result["room_mentions"] = self.extract_room_mentions(html)
        result["relevant_pages"] = self.find_relevant_pages(html, url)
        result["success"] = True
        
        return result
    
    async def deep_scrape_hotel(self, base_url: str, max_pages: int = 6) -> Dict[str, Any]:
        """
        Deep scrape a hotel website including subpages.
        Prioritizes contact and FAQ pages which often have phone numbers and room info.
        """
        # Start with the homepage
        main_result = await self.scrape_hotel_website(base_url)
        
        if not main_result["success"]:
            return main_result
        
        all_text = [main_result["text_content"]]
        all_phones = main_result["phone_numbers"]
        all_rooms = main_result["room_mentions"]
        pages_scraped = [base_url]
        
        # Also try common URL patterns for contact/FAQ if not found in links
        common_paths = ['/contact', '/contact-us', '/faq', '/faqs', '/about', '/about-us']
        additional_urls = []
        
        from urllib.parse import urlparse, urljoin
        parsed_base = urlparse(base_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
        
        for path in common_paths:
            potential_url = base_domain + path
            if potential_url not in main_result["relevant_pages"] and potential_url != base_url:
                additional_urls.append(potential_url)
        
        # Combine found pages with common paths, prioritizing found pages
        all_relevant_pages = main_result["relevant_pages"] + additional_urls
        
        # Scrape relevant subpages (increased limit for better coverage)
        for subpage_url in all_relevant_pages[:max_pages-1]:
            if subpage_url in pages_scraped:
                continue
            
            logger.info(f"Scraping subpage: {subpage_url}")
            subpage_result = await self.scrape_hotel_website(subpage_url)
            pages_scraped.append(subpage_url)
            
            if subpage_result["success"]:
                all_text.append(subpage_result["text_content"])
                
                # Merge phone numbers (avoid duplicates)
                for phone in subpage_result["phone_numbers"]:
                    if phone["formatted"] not in [p["formatted"] for p in all_phones]:
                        all_phones.append(phone)
                
                # Merge room mentions
                for room in subpage_result["room_mentions"]:
                    if room["count"] not in [r["count"] for r in all_rooms]:
                        all_rooms.append(room)
        
        logger.info(f"Deep scrape complete: {len(pages_scraped)} pages, {len(all_phones)} phones, {len(all_rooms)} room mentions")
        
        return {
            "url": base_url,
            "pages_scraped": pages_scraped,
            "text_content": "\n\n---PAGE BREAK---\n\n".join(all_text),
            "phone_numbers": all_phones,
            "room_mentions": all_rooms,
            "raw_html": main_result.get("raw_html", ""),  # Include raw HTML for parking detection
            "success": True
        }
    
    async def scrape_booking_site_for_rooms(
        self, 
        hotel_name: str, 
        city: Optional[str] = None,
        address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Scrape booking sites for room count information.
        Priority:
        1. City-specific booking aggregators (hotels-birmingham.net, etc.)
        2. Booking.com
        3. TripAdvisor
        
        Useful for smaller hotels that don't list room counts on their own site,
        or when the hotel's own website is a parked domain.
        """
        result = {
            "rooms_min": None,
            "rooms_max": None,
            "source": None,
            "source_notes": None,
            "phone": None,
            "success": False
        }
        
        # Determine minimum room threshold based on hotel type
        # Large chains would never have small room counts
        min_rooms = self._get_min_room_threshold(hotel_name)
        
        # Extract city from address if not provided
        effective_city = city
        if not effective_city and address:
            parts = address.split(',')
            if len(parts) > 1:
                effective_city = parts[-2].strip()  # Usually city is second-to-last
        
        logger.info(f"Searching booking sites for: {hotel_name} in {effective_city} (min rooms: {min_rooms})")
        
        # Try city-specific booking aggregator URLs (like hotels-birmingham.net)
        # These often have reliable room count information
        if effective_city:
            try:
                aggregator_result = await self._scrape_city_booking_aggregator(hotel_name, effective_city, min_rooms)
                if aggregator_result["success"]:
                    logger.info(f"Found hotel on city booking aggregator: {aggregator_result['source']}")
                    return aggregator_result
            except Exception as e:
                logger.warning(f"City booking aggregator scrape failed: {e}")
        
        # Build search query for other sites
        search_terms = [hotel_name]
        if effective_city:
            search_terms.append(effective_city)
        search_query = ' '.join(search_terms)
        
        # Try Booking.com search results
        try:
            booking_result = await self._scrape_booking_com(search_query, hotel_name, min_rooms)
            if booking_result["success"]:
                return booking_result
        except Exception as e:
            logger.warning(f"Booking.com scrape failed: {e}")
        
        # Try TripAdvisor as fallback
        try:
            tripadvisor_result = await self._scrape_tripadvisor(search_query, hotel_name, min_rooms)
            if tripadvisor_result["success"]:
                return tripadvisor_result
        except Exception as e:
            logger.warning(f"TripAdvisor scrape failed: {e}")
        
        return result
    
    async def _scrape_official_website_for_rooms(self, url: str, hotel_name: str) -> Dict[str, Any]:
        """
        Scrape the official hotel website for room count information.
        """
        result = {
            "success": False, 
            "rooms_min": None, 
            "rooms_max": None, 
            "source": None, 
            "source_notes": None, 
            "phone": None
        }
        
        min_rooms = self._get_min_room_threshold(hotel_name)
        
        try:
            # Fetch the main page
            html = await self.fetch_page(url)
            if not html:
                return result
            
            # Check for domain parking
            text_content = self.extract_text_content(html)
            parking_check = self.detect_domain_parking(html, text_content)
            if parking_check["is_parked"]:
                logger.info(f"Official website appears parked: {url}")
                return result
            
            # Extract room mentions from main page
            room_mentions = self.extract_room_mentions(html)
            
            # Also check key subpages (rooms, about, accommodation)
            subpages_to_try = []
            soup = BeautifulSoup(html, 'lxml')
            for link in soup.find_all('a', href=True):
                href = link.get('href', '').lower()
                link_text = link.get_text().lower()
                if any(kw in href or kw in link_text for kw in ['room', 'accommodation', 'about', 'suite']):
                    full_url = urljoin(url, link.get('href'))
                    if full_url not in subpages_to_try and len(subpages_to_try) < 3:
                        subpages_to_try.append(full_url)
            
            # Scrape subpages
            for subpage_url in subpages_to_try:
                try:
                    subpage_html = await self.fetch_page(subpage_url)
                    if subpage_html:
                        subpage_mentions = self.extract_room_mentions(subpage_html)
                        room_mentions.extend(subpage_mentions)
                except Exception as e:
                    logger.debug(f"Failed to scrape subpage {subpage_url}: {e}")
            
            # Find the most likely room count
            if room_mentions:
                # Filter and sort by confidence
                valid_mentions = [m for m in room_mentions if m["count"] >= min_rooms]
                if valid_mentions:
                    # Sort by confidence, then prefer smaller numbers (more likely to be actual room count)
                    valid_mentions.sort(key=lambda x: (-x["confidence"], x["count"]))
                    best_mention = valid_mentions[0]
                    
                    result["rooms_min"] = best_mention["count"]
                    result["rooms_max"] = best_mention["count"]
                    result["source"] = f"Official website ({urlparse(url).netloc})"
                    result["source_notes"] = f"Room count from official website: {best_mention['count']} rooms. Context: {best_mention['context'][:100]}"
                    result["success"] = True
                    logger.info(f"Found {best_mention['count']} rooms from official website {url}")
            
            # Extract phone if available
            if not result["phone"]:
                phones = self.extract_phone_numbers(html)
                if phones:
                    result["phone"] = phones[0]["formatted"]
            
            return result
            
        except Exception as e:
            logger.warning(f"Error scraping official website {url}: {e}")
            return result
    
    async def _scrape_city_booking_aggregator(self, hotel_name: str, city: str, min_rooms: int) -> Dict[str, Any]:
        """
        Try city-specific booking aggregator sites like hotels-birmingham.net.
        These sites often have reliable room count information for hotels.
        
        Pattern examples:
        - https://edgbastonpalace.hotels-birmingham.net/en/
        - https://thegrandhotel.hotels-brighton.net/en/
        """
        result = {
            "success": False, 
            "rooms_min": None, 
            "rooms_max": None, 
            "source": None, 
            "source_notes": None, 
            "phone": None
        }
        
        # Clean hotel name for URL generation - multiple variations
        clean_name_base = hotel_name.lower()
        
        # Create variations of the hotel name for URL patterns
        # Variation 1: Full name without spaces
        clean_full = re.sub(r'[^\w]', '', clean_name_base)
        
        # Variation 2: Without "the" prefix and "hotel" suffix only
        clean_no_the = clean_name_base
        if clean_no_the.startswith('the '):
            clean_no_the = clean_no_the[4:]
        if clean_no_the.endswith(' hotel'):
            clean_no_the = clean_no_the[:-6]
        clean_no_the = re.sub(r'[^\w]', '', clean_no_the)
        
        # Variation 3: Aggressively cleaned (for fallback)
        clean_aggressive = clean_name_base
        for word in ['the ', ' hotel', ' inn', ' lodge', ' house']:
            clean_aggressive = clean_aggressive.replace(word, '')
        clean_aggressive = re.sub(r'[^\w]', '', clean_aggressive)
        
        # Clean city name
        clean_city = re.sub(r'[^\w]', '', city.lower())
        
        # Generate URL patterns to try
        # IMPORTANT: Try without "hotel" suffix first as booking aggregators 
        # typically use shorter hotel names (edgbastonpalace not edgbastonpalacehotel)
        url_patterns = [
            # Try without "the" and "hotel" FIRST - e.g., "edgbastonpalace"
            f"https://{clean_no_the}.hotels-{clean_city}.net/en/",
            # Try with "the" prefix (for hotels like "The Grand")
            f"https://the{clean_no_the}.hotels-{clean_city}.net/en/",
            # Try with full name as fallback - e.g., "edgbastonpalacehotel"
            f"https://{clean_full}.hotels-{clean_city}.net/en/",
            # Try aggressive cleaning last - e.g., "edgbaston"
            f"https://{clean_aggressive}.hotels-{clean_city}.net/en/",
        ]
        
        # Remove duplicates while preserving order
        url_patterns = list(dict.fromkeys(url_patterns))
        
        logger.info(f"Trying city booking aggregator URLs for '{hotel_name}': {url_patterns}")
        
        for url in url_patterns:
            logger.info(f"Trying city booking aggregator: {url}")
            try:
                html = await self.fetch_page(url)
                if not html:
                    continue
                
                text_content = self.extract_text_content(html)
                text_lower = text_content.lower()
                
                # Verify this is actually a hotel page
                if not ('hotel' in text_lower or 'room' in text_lower or 'check-in' in text_lower):
                    logger.debug(f"Page doesn't look like a hotel page: {url}")
                    continue
                
                # Look for room count - these aggregators often have "X rooms" prominently displayed
                # Be careful to avoid matching "6 room types" or "6 rooms available tonight"
                room_patterns = [
                    # Total room count patterns (most reliable)
                    r'(?:total\s+(?:of\s+)?)?(\d+)\s*(?:guest\s+)?rooms?\s+(?:in\s+)?total',
                    r'(?:hotel|property)\s+(?:has|with|features?|offers?)\s+(\d+)\s*(?:guest\s+)?rooms?',
                    r'(\d+)\s*(?:guest\s+)?rooms?\s+(?:hotel|property)',
                    r'number\s+of\s+rooms?\s*[:\s]*(\d+)',
                    r'(\d+)\s+(?:comfortable|spacious|luxury|stylish|modern)\s+(?:guest\s+)?rooms?',
                    # Pattern for "250 rooms" when it's a larger number (likely total)
                    r'(?:^|\s)(\d{2,})\s*(?:guest\s+)?rooms?(?:\s|$|,|\.)',
                ]
                
                for pattern in room_patterns:
                    matches = re.findall(pattern, text_content, re.IGNORECASE)
                    for match in matches:
                        try:
                            count = int(match)
                            # Use dynamic threshold based on hotel type
                            # Chains need higher count, independents can be smaller
                            if count < min_rooms:
                                logger.debug(f"Skipping room count {count} - below min threshold of {min_rooms}")
                                continue
                            if min_rooms <= count <= 2000:  # Reasonable room count for total
                                result["rooms_min"] = count
                                result["rooms_max"] = count
                                result["source"] = url
                                result["source_notes"] = f"Room count found on city booking aggregator: {count} rooms"
                                result["success"] = True
                                logger.info(f"Found room count on city aggregator ({url}): {count} rooms")
                                
                                # Also try to extract phone number
                                phones = self.extract_phone_numbers(html)
                                if phones:
                                    result["phone"] = phones[0]["formatted"]
                                
                                return result
                        except ValueError:
                            continue
                
            except Exception as e:
                logger.debug(f"City aggregator URL failed: {url} - {e}")
                continue
        
        return result
    
    async def _scrape_booking_com(self, search_query: str, hotel_name: str, min_rooms: int) -> Dict[str, Any]:
        """Scrape Booking.com for hotel room information"""
        result = {"success": False, "rooms_min": None, "rooms_max": None, "source": None, "source_notes": None, "phone": None}
        
        # Search URL for Booking.com
        encoded_query = quote_plus(search_query)
        search_url = f"https://www.booking.com/searchresults.en-gb.html?ss={encoded_query}&dest_type=hotel"
        
        html = await self.fetch_page(search_url)
        if not html:
            return result
        
        text = self.extract_text_content(html)
        
        # Look for room count patterns in Booking.com format
        # Be careful to avoid matching "6 room types" or availability numbers
        patterns = [
            r'(?:total\s+(?:of\s+)?)?(\d+)\s*rooms?\s+(?:in\s+)?total',
            r'property\s+has\s+(\d+)\s*rooms?',
            r'(\d+)-room\s+(?:hotel|property)',
            r'featuring\s+(\d+)\s*(?:guest)?\s*rooms?',
            r'with\s+(\d+)\s*(?:en-suite)?\s*rooms?',
            r'(?:hotel|property)\s+(?:offers?|has)\s+(\d+)\s*rooms?',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                for match in matches:
                    count = int(match)
                    # Use dynamic threshold based on hotel type
                    if count < min_rooms:
                        logger.debug(f"Skipping room count {count} from Booking.com - below min threshold of {min_rooms}")
                        continue
                    if min_rooms <= count <= 2000:  # Reasonable total room count
                        result["rooms_min"] = count
                        result["rooms_max"] = count
                        result["source"] = "Booking.com"
                        result["source_notes"] = f"Room count found via Booking.com search: {count} rooms"
                        result["success"] = True
                        logger.info(f"Found room count on Booking.com: {count}")
                        return result
        
        return result
    
    async def _scrape_tripadvisor(self, search_query: str, hotel_name: str, min_rooms: int) -> Dict[str, Any]:
        """Scrape TripAdvisor for hotel room information"""
        result = {"success": False, "rooms_min": None, "rooms_max": None, "source": None, "source_notes": None, "phone": None}
        
        # TripAdvisor search URL
        encoded_query = quote_plus(search_query)
        search_url = f"https://www.tripadvisor.co.uk/Search?q={encoded_query}&searchSessionId=0"
        
        html = await self.fetch_page(search_url)
        if not html:
            return result
        
        text = self.extract_text_content(html)
        
        # TripAdvisor patterns - look for explicit room counts
        patterns = [
            r'NUMBER\s+OF\s+ROOMS\s*[:\s]*(\d+)',
            r'(\d+)\s*rooms?\s*(?:total|in\s+hotel)',
            r'(?:^|\s)rooms?\s*[:\s]*(\d+)(?:\s|$)',
            r'(?:hotel|property)\s+(?:has|with)\s+(\d+)\s*rooms?',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                for match in matches:
                    count = int(match)
                    # Use dynamic threshold based on hotel type
                    if count < min_rooms:
                        logger.debug(f"Skipping room count {count} from TripAdvisor - below min threshold of {min_rooms}")
                        continue
                    if min_rooms <= count <= 2000:
                        result["rooms_min"] = count
                        result["rooms_max"] = count
                        result["source"] = "TripAdvisor"
                        result["source_notes"] = f"Room count found via TripAdvisor: {count} rooms"
                        result["success"] = True
                        logger.info(f"Found room count on TripAdvisor: {count}")
                        return result
        
        # Also look for phone numbers on TripAdvisor
        phones = self.extract_phone_numbers(html)
        if phones:
            result["phone"] = phones[0]["formatted"]
        
        return result
