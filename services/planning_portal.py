"""
Planning Portal Search Service

Searches UK council planning portals for hotel planning applications
to find room counts as a last resort fallback.
"""

import logging
import re
import httpx
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class PlanningPortalService:
    """Service for searching UK council planning portals for hotel room information"""
    
    # Mapping of UK areas/postcodes to their planning portal search URLs
    # Format: prefix -> (portal_name, search_url_template, result_selector)
    PLANNING_PORTALS = {
        # West Midlands
        'B': {
            'name': 'Birmingham',
            'search_url': 'https://eplanning.birmingham.gov.uk/Northgate/PlanningExplorer/GeneralSearch.aspx',
            'type': 'northgate'
        },
        'B90': {
            'name': 'Solihull',
            'search_url': 'https://publicaccess.solihull.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'B91': {'name': 'Solihull', 'search_url': 'https://publicaccess.solihull.gov.uk/online-applications/search.do?action=simple', 'type': 'idox'},
        'B92': {'name': 'Solihull', 'search_url': 'https://publicaccess.solihull.gov.uk/online-applications/search.do?action=simple', 'type': 'idox'},
        'B93': {'name': 'Solihull', 'search_url': 'https://publicaccess.solihull.gov.uk/online-applications/search.do?action=simple', 'type': 'idox'},
        'B94': {'name': 'Solihull', 'search_url': 'https://publicaccess.solihull.gov.uk/online-applications/search.do?action=simple', 'type': 'idox'},
        'CV': {
            'name': 'Coventry',
            'search_url': 'https://planning.coventry.gov.uk/portal/servlets/ApplicationSearchServlet',
            'type': 'ocella'
        },
        
        # London
        'SW': {
            'name': 'Westminster',
            'search_url': 'https://idoxpa.westminster.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'W1': {
            'name': 'Westminster',
            'search_url': 'https://idoxpa.westminster.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'WC': {
            'name': 'Camden',
            'search_url': 'https://planningrecords.camden.gov.uk/Northgate/PlanningExplorer/GeneralSearch.aspx',
            'type': 'northgate'
        },
        'EC': {
            'name': 'City of London',
            'search_url': 'https://www.planning2.cityoflondon.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'SE': {
            'name': 'Southwark',
            'search_url': 'https://planning.southwark.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'NW': {
            'name': 'Camden',
            'search_url': 'https://planningrecords.camden.gov.uk/Northgate/PlanningExplorer/GeneralSearch.aspx',
            'type': 'northgate'
        },
        
        # South
        'BN': {
            'name': 'Brighton & Hove',
            'search_url': 'https://planningapps.brighton-hove.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'SO': {
            'name': 'Southampton',
            'search_url': 'https://planningpublicaccess.southampton.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'PO': {
            'name': 'Portsmouth',
            'search_url': 'https://publicaccess.portsmouth.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'RG': {
            'name': 'Reading',
            'search_url': 'https://planning.reading.gov.uk/fastweb_PL/welcome.asp',
            'type': 'fastweb'
        },
        'OX': {
            'name': 'Oxford',
            'search_url': 'https://public.oxford.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        
        # North
        'M': {
            'name': 'Manchester',
            'search_url': 'https://pa.manchester.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'L': {
            'name': 'Liverpool',
            'search_url': 'https://northgate.liverpool.gov.uk/PlanningExplorer/GeneralSearch.aspx',
            'type': 'northgate'
        },
        'LS': {
            'name': 'Leeds',
            'search_url': 'https://publicaccess.leeds.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'S': {
            'name': 'Sheffield',
            'search_url': 'https://planningapps.sheffield.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'NE': {
            'name': 'Newcastle',
            'search_url': 'https://publicaccess.newcastle.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        
        # Scotland
        'EH': {
            'name': 'Edinburgh',
            'search_url': 'https://citydev-portal.edinburgh.gov.uk/idoxpa-web/search.do?action=simple',
            'type': 'idox'
        },
        'G': {
            'name': 'Glasgow',
            'search_url': 'https://publicaccess.glasgow.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        
        # East
        'CB': {
            'name': 'Cambridge',
            'search_url': 'https://applications.greatercambridgeplanning.org/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'NR': {
            'name': 'Norwich',
            'search_url': 'https://planning.norwich.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        
        # Wales
        'CF': {
            'name': 'Cardiff',
            'search_url': 'https://planningonline.cardiff.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        
        # Bristol & Bath
        'BS': {
            'name': 'Bristol',
            'search_url': 'https://pa.bristol.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'BA': {
            'name': 'Bath & NE Somerset',
            'search_url': 'https://isharemaps.bathnes.gov.uk/ishare.web/planning.aspx',
            'type': 'idox'
        },
        
        # Yorkshire
        'YO': {
            'name': 'York',
            'search_url': 'https://planningaccess.york.gov.uk/online-applications/search.do?action=simple',
            'type': 'idox'
        },
        'HU': {
            'name': 'Hull',
            'search_url': 'https://www.hullcc.gov.uk/padcbc/publicaccess-live/search.do?action=simple',
            'type': 'idox'
        },
    }
    
    # Room count patterns to search for in planning descriptions
    ROOM_PATTERNS = [
        r'(\d+)\s*(?:bed)?rooms?\s*hotel',
        r'hotel\s*(?:with|of|comprising)?\s*(\d+)\s*(?:bed)?rooms?',
        r'(\d+)\s*(?:guest|letting)\s*rooms?',
        r'(\d+)\s*(?:bed)?room\s*(?:hotel|accommodation)',
        r'extension\s*(?:to\s*)?(?:provide|add|create)\s*(\d+)\s*(?:additional\s*)?(?:bed)?rooms?',
        r'(?:increase|expand)\s*(?:to|by)\s*(\d+)\s*(?:bed)?rooms?',
        r'total\s*(?:of\s*)?(\d+)\s*(?:bed)?rooms?',
        r'(\d+)\s*keys?',  # Hotel industry term for rooms
        r'c(?:lass)?\s*c1\s*(?:hotel|use)\s*(?:with\s*)?(\d+)\s*(?:bed)?rooms?',
    ]
    
    def __init__(self):
        self.http_client = httpx.Client(
            timeout=30.0,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            follow_redirects=True
        )
    
    def _get_portal_for_postcode(self, postcode: str) -> Optional[Dict]:
        """Find the appropriate planning portal for a postcode"""
        if not postcode:
            return None
            
        postcode = postcode.upper().strip().replace(' ', '')
        
        # Try most specific match first (e.g., B90 before B)
        for prefix_len in [3, 2, 1]:
            prefix = postcode[:prefix_len]
            if prefix in self.PLANNING_PORTALS:
                return self.PLANNING_PORTALS[prefix]
        
        return None
    
    def _get_portal_for_city(self, city: str) -> Optional[Dict]:
        """Find planning portal by city name"""
        if not city:
            return None
            
        city_lower = city.lower().strip()
        
        # Map city names to postcode prefixes
        city_to_prefix = {
            'london': 'SW',
            'westminster': 'SW',
            'birmingham': 'B',
            'solihull': 'B90',
            'manchester': 'M',
            'liverpool': 'L',
            'leeds': 'LS',
            'sheffield': 'S',
            'newcastle': 'NE',
            'bristol': 'BS',
            'brighton': 'BN',
            'bath': 'BA',
            'oxford': 'OX',
            'cambridge': 'CB',
            'york': 'YO',
            'edinburgh': 'EH',
            'glasgow': 'G',
            'cardiff': 'CF',
            'coventry': 'CV',
            'southampton': 'SO',
            'portsmouth': 'PO',
        }
        
        for city_name, prefix in city_to_prefix.items():
            if city_name in city_lower:
                return self.PLANNING_PORTALS.get(prefix)
        
        return None
    
    async def search_planning_portal(
        self,
        hotel_name: str,
        address: Optional[str] = None,
        city: Optional[str] = None,
        postcode: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Search planning portal for hotel applications that might contain room counts.
        
        Returns dict with room_count, source_url, and notes if found.
        """
        # Find appropriate portal
        portal = self._get_portal_for_postcode(postcode)
        if not portal:
            portal = self._get_portal_for_city(city)
        
        if portal:
            logger.info(f"Searching {portal['name']} planning portal for '{hotel_name}'")
            
            try:
                if portal['type'] == 'idox':
                    result = await self._search_idox_portal(portal, hotel_name, address, postcode)
                    if result:
                        return result
                elif portal['type'] == 'northgate':
                    result = await self._search_northgate_portal(portal, hotel_name, address, postcode)
                    if result:
                        return result
            except Exception as e:
                logger.warning(f"Error searching planning portal directly: {e}")
        
        # Fallback: Search for planning applications via web search
        logger.info(f"Trying web search for planning applications: {hotel_name}")
        return await self._search_via_web(hotel_name, city, postcode)
    
    async def _search_idox_portal(
        self,
        portal: Dict,
        hotel_name: str,
        address: Optional[str],
        postcode: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Search IDOX-based planning portal (most common in UK)"""
        
        # Build search query - try hotel name first, then address
        search_terms = [hotel_name]
        if address:
            # Extract street name
            street = address.split(',')[0].strip()
            search_terms.append(street)
        
        for search_term in search_terms:
            try:
                # IDOX simple search
                search_url = portal['search_url']
                params = {
                    'searchType': 'Application',
                    'searchCriteria.simpleSearchString': search_term,
                }
                
                response = self.http_client.get(search_url, params=params)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Find application links
                results = soup.select('a.searchresult, li.searchresult a, td.searchresults a')
                
                for result in results[:5]:  # Check first 5 results
                    app_url = result.get('href', '')
                    if not app_url.startswith('http'):
                        base_url = search_url.rsplit('/', 1)[0]
                        app_url = f"{base_url}/{app_url}"
                    
                    # Fetch application details
                    room_info = await self._extract_room_count_from_application(app_url, hotel_name)
                    if room_info:
                        return room_info
                        
            except Exception as e:
                logger.warning(f"Error searching IDOX portal: {e}")
                continue
        
        return None
    
    async def _search_northgate_portal(
        self,
        portal: Dict,
        hotel_name: str,
        address: Optional[str],
        postcode: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Search Northgate-based planning portal"""
        # Northgate portals are more complex, simplified implementation
        logger.info(f"Northgate portal search not fully implemented for {portal['name']}")
        return None
    
    async def _extract_room_count_from_application(
        self,
        app_url: str,
        hotel_name: str
    ) -> Optional[Dict[str, Any]]:
        """Extract room count from a planning application page"""
        try:
            response = self.http_client.get(app_url)
            if response.status_code != 200:
                return None
            
            text = response.text.lower()
            
            # Check if this application is related to the hotel
            hotel_name_lower = hotel_name.lower()
            name_parts = hotel_name_lower.replace('the ', '').replace('hotel', '').split()
            
            # Must match at least part of the hotel name
            if not any(part in text for part in name_parts if len(part) > 2):
                return None
            
            # Search for room counts in the application text
            for pattern in self.ROOM_PATTERNS:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    try:
                        room_count = int(match)
                        if 5 <= room_count <= 2000:  # Reasonable hotel size
                            logger.info(f"Found room count {room_count} in planning application")
                            return {
                                'room_count': room_count,
                                'source_url': app_url,
                                'source': 'planning_portal',
                                'notes': f'Room count found in planning application'
                            }
                    except (ValueError, TypeError):
                        continue
                        
        except Exception as e:
            logger.warning(f"Error extracting from application: {e}")
        
        return None
    
    def _search_via_google(
        self,
        hotel_name: str,
        portal_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback: Search Google for planning applications.
        Uses site-specific search to find applications.
        """
        # This could be implemented using DuckDuckGo search with site: operator
        # For now, return None
        return None
    
    async def _search_via_web(
        self,
        hotel_name: str,
        city: Optional[str] = None,
        postcode: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Search for planning applications via web search.
        Uses Azure Bing Search API if configured, otherwise falls back to DuckDuckGo.
        """
        from config import AZURE_BING_SEARCH_KEY, AZURE_BING_SEARCH_ENDPOINT, USE_AZURE_BING_SEARCH
        
        # Build search query
        location = city or postcode or ""
        query = f'"{hotel_name}" planning application hotel rooms {location}'
        
        results = []
        
        # Try Azure Bing Search API first (if configured)
        if USE_AZURE_BING_SEARCH:
            try:
                headers = {'Ocp-Apim-Subscription-Key': AZURE_BING_SEARCH_KEY}
                params = {'q': query, 'count': 5, 'mkt': 'en-GB'}
                
                response = self.http_client.get(
                    AZURE_BING_SEARCH_ENDPOINT,
                    headers=headers,
                    params=params
                )
                response.raise_for_status()
                
                data = response.json()
                web_pages = data.get('webPages', {}).get('value', [])
                
                for item in web_pages:
                    results.append({
                        'href': item.get('url', ''),
                        'title': item.get('name', ''),
                        'body': item.get('snippet', '')
                    })
                    
                logger.info(f"Azure Bing API returned {len(results)} planning search results")
                
            except Exception as e:
                logger.warning(f"Azure Bing Search failed for planning portal: {e}")
        
        # Fallback to DuckDuckGo
        if not results:
            try:
                from duckduckgo_search import DDGS
                ddgs = DDGS()
                ddg_results = ddgs.text(query, max_results=5)
                
                for result in ddg_results:
                    results.append({
                        'href': result.get('href', ''),
                        'title': result.get('title', ''),
                        'body': result.get('body', '')
                    })
                    
            except Exception as e:
                logger.warning(f"DuckDuckGo search for planning applications failed: {e}")
        
        # Process results
        for result in results:
            url = result.get('href', '')
            title = result.get('title', '').lower()
            body = result.get('body', '').lower()
            
            # Check if this looks like a planning portal result
            planning_indicators = [
                'planning', 'application', 'publicaccess', 
                'online-applications', 'council', 'gov.uk'
            ]
            
            if not any(ind in url.lower() or ind in title for ind in planning_indicators):
                continue
            
            # Check the result text for room count mentions
            combined_text = f"{title} {body}"
            room_count = self._extract_room_count_from_text(combined_text, hotel_name)
            
            if room_count:
                logger.info(f"Found room count {room_count} in web search result: {url}")
                return {
                    'room_count': room_count,
                    'source_url': url,
                    'source': 'planning_portal_search',
                    'notes': 'Room count found via web search of planning records'
                }
            
            # Try fetching the page for more details
            try:
                page_result = await self._extract_room_count_from_application(url, hotel_name)
                if page_result:
                    return page_result
            except Exception:
                continue
        
        return None
    
    def _extract_room_count_from_text(
        self,
        text: str,
        hotel_name: str
    ) -> Optional[int]:
        """Extract room count from text if it appears to be about the hotel"""
        text_lower = text.lower()
        hotel_name_lower = hotel_name.lower()
        
        # Check if text is about this hotel
        name_parts = hotel_name_lower.replace('the ', '').replace('hotel', '').split()
        if not any(part in text_lower for part in name_parts if len(part) > 2):
            return None
        
        # Look for room counts
        for pattern in self.ROOM_PATTERNS:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                try:
                    room_count = int(match)
                    if 5 <= room_count <= 2000:  # Reasonable hotel size
                        return room_count
                except (ValueError, TypeError):
                    continue
        
        return None
