# Hotel Information Extraction API

An AI-powered containerized API that extracts hotel information (room counts, phone numbers, websites) from hotel websites based on name and address.

## Features

- 🔍 **Bing Grounding Search**: Uses Azure AI Foundry agent with Bing Grounding to find hotel information
- 🤖 **AI-Powered Agent**: HotelTVSearch agent searches and extracts data in a single step
- 🕷️ **Smart Web Scraping**: Optionally deep-scrapes hotel websites for additional data
- 🧠 **AI Extraction**: Uses Azure OpenAI GPT to extract structured data from unstructured content
- 📞 **UK Phone Validation**: Validates and formats UK phone numbers
- 📊 **Confidence Scoring**: Provides confidence scores for extracted data
- 🐳 **Containerized**: Deployed on Azure Container Apps
- 💾 **Redis Caching**: Caches results with configurable TTL

## How It Works - Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        HOTEL INFORMATION EXTRACTION                          │
│                              WORKFLOW DIAGRAM                                │
└─────────────────────────────────────────────────────────────────────────────┘

    INPUT                                                              OUTPUT
    ─────                                                              ──────
┌───────────────┐                                              ┌───────────────┐
│ Hotel Name    │                                              │ Website URL   │
│ Address/City  │ ──────────────────────────────────────────▶  │ Phone Number  │
│ Postcode      │                                              │ Room Count    │
└───────────────┘                                              │ Source Notes  │
                                                               └───────────────┘

                         ┌─────────────────────┐
                         │   STEP 1: SEARCH    │
                         │   ───────────────   │
                         │ • Bing Grounding    │
                         │   Agent searches    │
                         │   the web via Bing  │
                         │ • Returns website,  │
                         │   phone, rooms      │
                         │ • Fallback: SerpAPI │
                         │   / DuckDuckGo      │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  STEP 2: VALIDATE   │
                         │  ────────────────   │
                         │ • HTTP HEAD request │
                         │ • Check URL works   │
                         │ • Follow redirects  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   STEP 3: SCRAPE    │
                         │   ──────────────    │
                         │ • Fetch homepage    │
                         │ • Find subpages     │
                         │   (rooms, contact,  │
                         │    about)           │
                         │ • Scrape up to 4    │
                         │   pages total       │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  STEP 4: EXTRACT    │
                         │  ────────────────   │
                         │ • Pre-extract       │
                         │   phone patterns    │
                         │ • Pre-extract       │
                         │   room mentions     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  STEP 5: AI VERIFY  │
                         │  ────────────────   │
                         │ • GPT verifies      │
                         │   correct hotel     │
                         │ • Checks name/      │
                         │   location match    │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ STEP 6: AI EXTRACT  │
                         │ ─────────────────   │
                         │ • GPT analyzes all  │
                         │   scraped content   │
                         │ • Extracts room     │
                         │   count (min/max)   │
                         │ • Selects best      │
                         │   phone number      │
                         │ • Provides source   │
                         │   notes & confidence│
                         └─────────────────────┘
```

### Detailed Step Descriptions

| Step | Component | Description |
|------|-----------|-------------|
| **1. Search** | `BingGroundingService` | Uses Azure AI Foundry HotelTVSearch agent with Bing Grounding to search the web. The agent can return the official website, phone number, and room count in a single call. Falls back to SerpAPI/DuckDuckGo if Bing Grounding is unavailable. |
| **2. Validate** | `WebSearchService` | Tests candidate URLs with HTTP HEAD requests to verify they're accessible and respond correctly. |
| **3. Scrape** | `WebScraperService` | Fetches the homepage HTML, then identifies and scrapes relevant subpages (rooms, accommodation, contact, about). Extracts clean text from up to 4 pages. |
| **4. Extract** | `WebScraperService` | Pre-processes content using regex patterns to identify phone numbers (validated as UK format) and room count mentions (e.g., "150 rooms", "200 bedrooms"). |
| **5. AI Verify** | `AIExtractorService` | Uses GPT to verify the scraped website matches the hotel being searched. Checks if hotel name and location appear in the content. |
| **6. AI Extract** | `AIExtractorService` | GPT analyzes all content and pre-extracted candidates to determine: room count (min/max), best UK phone number, and provides source notes explaining where data was found. Returns a confidence score. |

## Quick Start

### 1. Set up environment variables

Create a `.env` file with your API keys:

```bash
# Azure OpenAI (required)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_DEPLOYMENT=gpt-4

# Azure AI Foundry - Bing Grounding (primary search)
AZURE_AI_PROJECT_ENDPOINT=https://your-foundry.services.ai.azure.com/api/projects/yourproject
BING_CONNECTION_NAME=your-bing-connection
USE_BING_GROUNDING=true

# SerpAPI (fallback only, optional)
# SERPAPI_API_KEY=your-serpapi-key
```

### 2. Run with Docker

```bash
docker-compose up --build
```

Or run locally:

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

### 3. Access the API

- **Swagger UI**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## API Endpoints

### Single Hotel Lookup

```bash
POST /api/v1/hotel/lookup
```

**Request:**
```json
{
    "name": "The Grand Hotel",
    "address": "1 King Street",
    "city": "Brighton",
    "postcode": "BN1 2FW"
}
```

**Response:**
```json
{
    "search_name": "The Grand Hotel",
    "search_address": "1 King Street, Brighton, BN1 2FW",
    "official_website": "https://www.grandbrighton.co.uk",
    "uk_contact_phone": "+44 1273 224300",
    "rooms_min": 201,
    "rooms_max": 201,
    "rooms_source_notes": "Found on About page: '201 luxurious bedrooms'",
    "website_source_url": "Bing Grounding",
    "phone_source_url": "https://www.grandbrighton.co.uk/contact",
    "status": "success",
    "last_checked": "2024-02-06T10:30:00Z",
    "confidence_score": 0.95,
    "errors": []
}
```

### Batch Lookup

```bash
POST /api/v1/hotel/batch
```

**Request:**
```json
{
    "hotels": [
        {"name": "The Grand Hotel", "city": "Brighton"},
        {"name": "The Ritz", "city": "London"},
        {"name": "Gleneagles", "city": "Perthshire"}
    ]
}
```

## Response Fields

| Field | Description |
|-------|-------------|
| `official_website` | Hotel's official website URL |
| `uk_contact_phone` | UK contact/reservations phone number |
| `rooms_min` | Minimum room count (or exact count) |
| `rooms_max` | Maximum room count (or exact count) |
| `rooms_source_notes` | How/where the room count was found |
| `website_source_url` | How the website was discovered |
| `phone_source_url` | Page where phone was found |
| `status` | `success`, `partial`, `not_found`, or `error` |
| `confidence_score` | AI confidence (0.0 - 1.0) |
| `errors` | List of any issues encountered |

## Status Codes

- `success`: All information found with high confidence
- `partial`: Some information found, but not all
- `not_found`: Could not find the hotel or its website
- `error`: An error occurred during processing

## Cost Estimation

**Azure OpenAI (GPT-4):**
- ~$0.001 - $0.005 per hotel lookup
- For 10,000 hotels: ~$10-50

**SerpAPI (fallback only):**
- Only used when Bing Grounding is unavailable
- 100 free searches/month
- Paid plans from $50/month for 5,000 searches

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | - |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key | - |
| `AZURE_OPENAI_DEPLOYMENT` | Azure deployment name | `gpt-4` |
| `AZURE_AI_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint | - |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model for Bing grounding agent | `gpt-5.2-chat` |
| `BING_CONNECTION_NAME` | Name of Bing connection in AI Foundry | - |
| `USE_BING_GROUNDING` | Enable/disable Bing grounding | `true` |
| `SERPAPI_API_KEY` | SerpAPI key (fallback search) | - |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `REDIS_ENABLED` | Enable/disable Redis caching | `true` |
| `CACHE_TTL_HOURS` | Cache time-to-live in hours | `24` |
| `MAX_REQUESTS_PER_MINUTE` | Rate limit | `30` |
| `SCRAPE_TIMEOUT_SECONDS` | Web scrape timeout | `30` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Redis Caching

The API uses Redis to cache hotel lookup results, significantly improving performance for repeated queries.

### Cache Behavior
- **TTL**: Results are cached for 24 hours by default
- **Cache Key**: Generated from hotel name + address (MD5 hash)
- **Skip Cache**: Add `?skip_cache=true` to force fresh lookup

### Cache Endpoints

```bash
# Get cache statistics
GET /cache/stats

# Invalidate cache for a hotel
DELETE /cache/invalidate?hotel_name=The%20Ritz%20London
```

### Running with Docker Compose

Redis is automatically started with docker-compose:

```bash
docker-compose up --build
```

### Disabling Cache

Set `REDIS_ENABLED=false` in environment variables to disable caching.

## Limitations

1. **Website Accuracy**: May not always find the correct official website for smaller hotels
2. **Room Data Availability**: Not all hotel websites list room counts
3. **Rate Limiting**: External APIs (search, scraping) have rate limits
4. **Processing Time**: Each lookup takes 10-30 seconds due to multiple web requests and AI calls

## Playwright (JavaScript Rendering)

The API uses Playwright to handle JavaScript-heavy websites (SPAs, React, Vue, Angular sites) that don't render content with standard HTTP requests.

### How It Works
1. First tries standard HTTP request (fast)
2. Detects if content is minimal or has SPA markers
3. Automatically falls back to Playwright (headless Chromium)
4. Returns whichever method produces more content

### Features
- **Automatic detection** of JS-heavy sites
- **Cookie consent handling** - dismisses common consent popups
- **Resource blocking** - blocks images/ads for faster loading
- **Smart fallback** - only uses browser when needed

### Docker Image Size
The Docker image includes Chromium browser (~400MB added). To disable Playwright:
- Remove `playwright>=1.40.0` from requirements.txt
- Remove Playwright-related lines from Dockerfile

## Error Handling

The API handles errors gracefully and returns appropriate status codes:

| Status | Meaning |
|--------|---------|
| `success` | All requested information found with high confidence |
| `partial` | Some information found (e.g., website found but no room count) |
| `not_found` | Could not find the hotel or its website |
| `error` | An error occurred during processing |

## Improvements for Production

1. ~~**Add Redis caching** to avoid re-scraping recent lookups~~ ✅ Implemented
2. ~~**Add Playwright/Selenium** for JavaScript-rendered sites~~ ✅ Implemented
3. **Add retry queues** for failed lookups
4. **Add webhook support** for async batch processing
5. **Add authentication** (API keys, OAuth)

## Project Structure

```
HotelTVLicensing/
├── main.py                 # FastAPI application & endpoints
├── config.py               # Configuration settings
├── models.py               # Pydantic request/response models
├── services/
│   ├── __init__.py
│   ├── bing_grounding_service.py  # Bing Grounding agent (primary search)
│   ├── cache_service.py    # Redis caching service
│   ├── playwright_service.py # Playwright for JS-rendered sites
│   ├── web_search.py       # Fallback: SerpAPI/DuckDuckGo search
│   ├── web_scraper.py      # Scraping & pre-extraction
│   ├── ai_extractor.py     # AI verification & extraction (Azure OpenAI)
│   └── hotel_lookup.py     # Orchestrates the full workflow
├── Dockerfile              # Container definition
├── docker-compose.yml      # Container orchestration
├── requirements.txt        # Python dependencies
├── test_api.py             # Test script
└── .env                    # Environment variables (API keys)
```

## Example: Full Lookup

**Input:**
```json
{
    "name": "The Grand Hotel Brighton",
    "city": "Brighton"
}
```

**Workflow Log:**
```
1. SEARCH    → Bing Grounding Agent: "The Grand Hotel Brighton"
             → Found website, phone, rooms via Bing search
2. VALIDATE  → Official website confirmed: https://www.grandbrighton.co.uk
3. SCRAPE    → Deep-scraped 3 pages for additional data
4. EXTRACT   → Pre-extracted: 2 phone candidates, 3 room mentions
5. AI VERIFY → GPT confirmed: Website matches "The Grand Hotel Brighton"
6. AI EXTRACT→ GPT analyzed content, confidence: 0.85
```

**Output:**
```json
{
  "official_website": "https://www.grandbrighton.co.uk",
  "uk_contact_phone": "+44 1273 224300",
  "rooms_min": 201,
  "rooms_max": 201,
  "rooms_source_notes": "Found on About page: '201 luxurious bedrooms'",
  "website_source_url": "Google Hotels",
  "status": "success",
  "confidence_score": 0.85
}
```

## License

MIT
