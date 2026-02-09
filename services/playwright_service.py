"""Playwright service for scraping JavaScript-rendered websites"""

import logging
import asyncio
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. JavaScript rendering will be unavailable.")


class PlaywrightService:
    """
    Service for scraping JavaScript-rendered websites using Playwright.
    
    Uses headless Chromium browser to render pages that rely on JavaScript
    for content loading (SPAs, React, Vue, Angular sites).
    
    Features:
    - Automatic page rendering with configurable wait
    - Screenshot capability for debugging
    - Cookie consent handling
    - Resource blocking for faster loading
    """
    
    # Common cookie consent button selectors
    COOKIE_CONSENT_SELECTORS = [
        'button:has-text("Accept")',
        'button:has-text("Accept All")',
        'button:has-text("Accept Cookies")',
        'button:has-text("I Accept")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        'button:has-text("Agree")',
        '[id*="accept"]',
        '[class*="accept"]',
        '[id*="consent"]',
        '[class*="cookie"] button',
    ]
    
    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._initialized = False
    
    @property
    def is_available(self) -> bool:
        """Check if Playwright is available"""
        return PLAYWRIGHT_AVAILABLE
    
    async def initialize(self) -> bool:
        """Initialize Playwright browser"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available - cannot initialize")
            return False
        
        if self._initialized:
            return True
        
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                ]
            )
            self._initialized = True
            logger.info("Playwright browser initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Playwright: {e}")
            return False
    
    async def close(self):
        """Close browser and cleanup"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._initialized = False
        logger.info("Playwright browser closed")
    
    @asynccontextmanager
    async def _get_page(self):
        """Context manager to get a new page"""
        if not self._initialized:
            await self.initialize()
        
        if not self._browser:
            raise RuntimeError("Browser not initialized")
        
        context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-GB',
            timezone_id='Europe/London',
        )
        
        # Block unnecessary resources for faster loading
        await context.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,eot}", lambda route: route.abort())
        await context.route("**/analytics**", lambda route: route.abort())
        await context.route("**/tracking**", lambda route: route.abort())
        await context.route("**/ads**", lambda route: route.abort())
        
        page = await context.new_page()
        
        try:
            yield page
        finally:
            await context.close()
    
    async def _handle_cookie_consent(self, page: Page):
        """Try to dismiss cookie consent popups"""
        for selector in self.COOKIE_CONSENT_SELECTORS:
            try:
                button = page.locator(selector).first
                if await button.is_visible(timeout=1000):
                    await button.click(timeout=2000)
                    logger.debug(f"Clicked cookie consent button: {selector}")
                    await page.wait_for_timeout(500)  # Wait for popup to close
                    return True
            except:
                continue
        return False
    
    async def fetch_rendered_page(
        self, 
        url: str, 
        wait_for_selector: Optional[str] = None,
        wait_for_network_idle: bool = True,
        take_screenshot: bool = False
    ) -> Dict[str, Any]:
        """
        Fetch a page with JavaScript rendering.
        
        Args:
            url: The URL to fetch
            wait_for_selector: Optional CSS selector to wait for
            wait_for_network_idle: Wait for network to be idle
            take_screenshot: Capture screenshot for debugging
            
        Returns:
            Dict with 'html', 'text', 'success', 'error', 'screenshot' (if requested)
        """
        if not PLAYWRIGHT_AVAILABLE:
            return {
                "success": False,
                "error": "Playwright not available",
                "html": None,
                "text": None
            }
        
        try:
            async with self._get_page() as page:
                # Navigate to the page
                logger.info(f"Playwright: Fetching {url}")
                
                response = await page.goto(
                    url, 
                    timeout=self.timeout_ms,
                    wait_until='domcontentloaded'
                )
                
                if not response or response.status >= 400:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status if response else 'No response'}",
                        "html": None,
                        "text": None
                    }
                
                # Wait for network to settle (for AJAX content)
                if wait_for_network_idle:
                    try:
                        await page.wait_for_load_state('networkidle', timeout=10000)
                    except PlaywrightTimeout:
                        logger.debug("Network idle timeout - continuing anyway")
                
                # Try to handle cookie consent
                await self._handle_cookie_consent(page)
                
                # Wait for specific selector if provided
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(wait_for_selector, timeout=5000)
                    except PlaywrightTimeout:
                        logger.debug(f"Selector {wait_for_selector} not found - continuing anyway")
                
                # Extra wait for JS rendering
                await page.wait_for_timeout(2000)
                
                # Get HTML content
                html = await page.content()
                
                # Get visible text
                text = await page.evaluate("""
                    () => {
                        // Remove script and style elements
                        const scripts = document.querySelectorAll('script, style, noscript');
                        scripts.forEach(el => el.remove());
                        
                        // Get text content
                        return document.body.innerText;
                    }
                """)
                
                result = {
                    "success": True,
                    "error": None,
                    "html": html,
                    "text": text,
                    "url": page.url  # Final URL after redirects
                }
                
                # Take screenshot if requested
                if take_screenshot:
                    result["screenshot"] = await page.screenshot(type='png')
                
                logger.info(f"Playwright: Successfully fetched {url} ({len(html)} bytes)")
                return result
                
        except PlaywrightTimeout as e:
            logger.warning(f"Playwright timeout for {url}: {e}")
            return {
                "success": False,
                "error": f"Timeout: {str(e)}",
                "html": None,
                "text": None
            }
        except Exception as e:
            logger.error(f"Playwright error for {url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "html": None,
                "text": None
            }
    
    async def is_js_heavy_site(self, html: str, text_content: str) -> bool:
        """
        Detect if a site likely requires JavaScript rendering.
        
        Checks for:
        - Very little text content despite HTML
        - React/Vue/Angular markers
        - Loading indicators
        """
        # Check for minimal text relative to HTML size
        html_size = len(html) if html else 0
        text_size = len(text_content) if text_content else 0
        
        if html_size > 5000 and text_size < 500:
            logger.debug("Detected potential JS-heavy site: HTML > 5KB but text < 500 chars")
            return True
        
        # Check for SPA framework markers
        spa_markers = [
            'id="root"', 'id="app"', 'id="__next"',  # React/Next.js
            'ng-app', 'ng-controller', '[ng-',  # Angular
            'data-v-', 'v-if', 'v-for',  # Vue
            '__NUXT__', '__NEXT_DATA__',  # Nuxt/Next
            'window.__PRELOADED_STATE__',  # Redux
            'Loading...', 'Please wait',  # Loading indicators
        ]
        
        html_lower = html.lower() if html else ''
        for marker in spa_markers:
            if marker.lower() in html_lower:
                logger.debug(f"Detected SPA marker: {marker}")
                return True
        
        return False


# Singleton instance
_playwright_service: Optional[PlaywrightService] = None


def get_playwright_service() -> PlaywrightService:
    """Get the global Playwright service instance"""
    global _playwright_service
    if _playwright_service is None:
        _playwright_service = PlaywrightService()
    return _playwright_service
