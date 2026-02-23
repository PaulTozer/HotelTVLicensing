# Hotel Information Extraction API

An AI-powered containerized API that extracts hotel information (room counts, phone numbers, websites) from hotel websites based on name and address.

## Features

- **Bing Grounding Search**: Uses Azure AI Foundry agent with Bing Grounding to find hotel information
- **AI-Powered Agent**: HotelTVSearch agent searches and extracts data in a single step
- **Smart Web Scraping**: Optionally deep-scrapes hotel websites for additional data
- **AI Extraction**: Uses Azure OpenAI GPT to extract structured data from unstructured content
- **UK Phone Validation**: Validates and formats UK phone numbers
- **Confidence Scoring**: Provides confidence scores for extracted data
- **Containerized**: Deployed on Azure Container Apps
- **Redis Caching**: Caches results with configurable TTL

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
| **1. Search** | `BingGroundingService` | Uses Azure AI Foundry HotelTVSearch agent with Bing Grounding to search the web. The agent can return the official website, phone number, and room count in a single call. |
| **2. Validate** | `HotelLookupService` | Tests candidate URLs with HTTP HEAD requests to verify they're accessible and respond correctly. |
| **3. Scrape** | `WebScraperService` | Fetches the homepage HTML, then identifies and scrapes relevant subpages (rooms, accommodation, contact, about). Extracts clean text from up to 4 pages. |
| **4. Extract** | `WebScraperService` | Pre-processes content using regex patterns to identify phone numbers (validated as UK format) and room count mentions (e.g., "150 rooms", "200 bedrooms"). |
| **5. AI Verify** | `AIExtractorService` | Uses GPT to verify the scraped website matches the hotel being searched. Checks if hotel name and location appear in the content. |
| **6. AI Extract** | `AIExtractorService` | GPT analyzes all content and pre-extracted candidates to determine: room count (min/max), best UK phone number, and provides source notes explaining where data was found. Returns a confidence score. |

## Prerequisites

Before deploying, you need to set up the following Azure resources:

### 1. Azure OpenAI Service

- Create an Azure OpenAI resource (Sweden Central recommended)
- Deploy a model (e.g., `gpt-5.2-chat` or `gpt-4`) for AI extraction
- Note down the **endpoint** and **API key**

### 2. Azure AI Foundry Project

The API uses an Azure AI Foundry agent with Bing Grounding to search for hotel information.

1. Go to [Azure AI Foundry](https://ai.azure.com)
2. Create or select a project
3. Note the **project endpoint** (e.g., `https://your-foundry.services.ai.azure.com/api/projects/yourproject`)

### 3. Bing Grounding Connection

1. In your Azure AI Foundry project, go to **Connected resources**
2. Add a **Bing Search** connection (requires a Bing Search resource in Azure)
3. Note the **connection name** (e.g., `my-bing-grounding`)

### 4. Model Deployment for Bing Agent

- Deploy `gpt-4.1-mini` in your AI Foundry project
- **Important**: Only `gpt-4.1-mini` works reliably with Bing Grounding tools. Other models (e.g., `gpt-5.2-chat`, `gpt-4.1`) may return errors.

See [FOUNDRY_SETUP.md](FOUNDRY_SETUP.md) for detailed step-by-step instructions on setting up the Azure AI Foundry agent.

## Quick Start (Local Development)

### 1. Set up environment variables

Create a `.env` file:

```bash
# Azure OpenAI (required for AI extraction)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_DEPLOYMENT=gpt-4

# Azure AI Foundry - Bing Grounding (required for search)
AZURE_AI_PROJECT_ENDPOINT=https://your-foundry.services.ai.azure.com/api/projects/yourproject
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4.1-mini
BING_CONNECTION_NAME=your-bing-connection
USE_BING_GROUNDING=true
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

## Deploying to Azure

### Step 1: Install Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) (v2.50+)
- An active Azure subscription
- Azure OpenAI resource with a deployed model
- Azure AI Foundry project with Bing Grounding connection (see Prerequisites above)

### Step 2: Log in to Azure

```powershell
az login
```

### Step 3: Run the deployment script

```powershell
.\deploy.ps1 `
    -ResourceGroupName "rg-hotel-api-swedencentral" `
    -AzureOpenAiApiKey "your-azure-openai-api-key" `
    -AzureOpenAiEndpoint "https://your-resource.openai.azure.com/" `
    -AzureAiProjectEndpoint "https://your-foundry.services.ai.azure.com/api/projects/yourproject" `
    -BingConnectionName "my-bing-grounding" `
    -AzureAiModelDeployment "gpt-4.1-mini"
```

#### deploy.ps1 Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `ResourceGroupName` | No | `rg-hotel-api-swedencentral` | Azure resource group name |
| `AzureOpenAiApiKey` | **Yes** | - | Azure OpenAI API key |
| `AzureAiProjectEndpoint` | **Yes** | - | Azure AI Foundry project endpoint |
| `BingConnectionName` | **Yes** | - | Bing Grounding connection name in AI Foundry |
| `AzureAiModelDeployment` | No | `gpt-4.1-mini` | Model for Bing Grounding agent |
| `AzureOpenAiEndpoint` | **Yes** | - | Azure OpenAI endpoint (e.g., `https://your-resource.openai.azure.com/`) |
| `AzureOpenAiDeployment` | No | `gpt-4` | Azure OpenAI deployment for AI extraction |
| `DeployBingSearch` | No | `false` | Switch to create a Bing Search v7 resource |
| `BingSearchSku` | No | `S1` | Bing Search pricing tier (`S1` or `F1` free) |
| `Location` | No | `swedencentral` | Azure region |
| `BaseName` | No | `hotelapi` | Base name for Azure resources |

### Step 4: Verify deployment

```bash
# Check health
curl https://<your-app-url>/health

# Test a lookup
curl -X POST https://<your-app-url>/api/v1/hotel/lookup \
  -H "Content-Type: application/json" \
  -d '{"name": "The Grand Hotel", "city": "Brighton"}'
```

### What the deployment creates

The `deploy.ps1` script and Bicep template create:

1. **Resource Group** in Sweden Central
2. **Azure Container Registry** (Basic SKU) — stores the Docker image
3. **Log Analytics Workspace** — collects container logs
4. **Container Apps Environment** — managed Kubernetes environment
5. **Container App** — runs the API with:
   - External HTTPS ingress on port 8000
   - Auto-scaling 0-3 replicas based on HTTP load
   - All Azure OpenAI and Foundry configuration passed as environment variables
6. **Bing Search v7** (optional, with `-DeployBingSearch`) — provides Bing API access for the grounding agent. After deployment, connect it to your AI Foundry project manually.

### Infrastructure as Code

The infrastructure is defined in Bicep:

- [infra/main.bicep](infra/main.bicep) — Container Registry, Container Apps Environment, Container App
- [infra/main.parameters.json](infra/main.parameters.json) — Parameter values (optional)

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
POST /api/v1/hotel/batch?fast=true
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

**Performance estimates:**
- 25 hotels (fast mode): ~20-30 seconds
- 25 hotels (full mode): ~60-120 seconds
- 100 hotels (fast mode): ~1-2 minutes
- 500 hotels (fast mode): ~5-10 minutes

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

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | - |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key | - |
| `AZURE_OPENAI_DEPLOYMENT` | Azure deployment name | `gpt-4` |
| `AZURE_OPENAI_FALLBACK_DEPLOYMENT` | Fallback model deployment | `gpt-4.1-mini` |
| `AZURE_AI_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint | - |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model for Bing grounding agent | `gpt-4.1-mini` |
| `BING_CONNECTION_NAME` | Bing connection name in AI Foundry | - |
| `USE_BING_GROUNDING` | Enable/disable Bing grounding | `true` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `REDIS_ENABLED` | Enable/disable Redis caching | `true` |
| `CACHE_TTL_HOURS` | Cache time-to-live in hours | `24` |
| `MAX_REQUESTS_PER_MINUTE` | Rate limit | `60` |
| `SCRAPE_TIMEOUT_SECONDS` | Web scrape timeout | `30` |
| `BATCH_MAX_CONCURRENT` | Max concurrent lookups | `25` |
| `BATCH_MAX_SIZE` | Max batch size | `500` |
| `BING_MAX_CONCURRENT` | Max concurrent Bing searches | `15` |
| `BING_THREAD_POOL_SIZE` | Thread pool for blocking SDK calls | `20` |
| `BING_RETRY_MAX` | Max retries for Bing agent | `3` |
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

## Playwright (JavaScript Rendering)

The API uses Playwright to handle JavaScript-heavy websites (SPAs, React, Vue, Angular sites) that don't render content with standard HTTP requests.

### How It Works
1. First tries standard HTTP request (fast)
2. Detects if content is minimal or has SPA markers
3. Automatically falls back to Playwright (headless Chromium)
4. Returns whichever method produces more content

## Cost Estimation

**Azure OpenAI (GPT-4):**
- ~$0.001 - $0.005 per hotel lookup
- For 10,000 hotels: ~$10-50

**Azure AI Foundry (Bing Grounding Agent):**
- Bing Search API pricing applies (based on your Bing Search resource tier)
- Agent API calls use the deployed model's token pricing

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
│   ├── web_scraper.py      # Scraping & pre-extraction
│   ├── ai_extractor.py     # AI verification & extraction (Azure OpenAI)
│   ├── planning_portal.py  # Planning portal fallback
│   └── hotel_lookup.py     # Orchestrates the full workflow
├── infra/
│   ├── main.bicep          # Azure infrastructure (Bicep)
│   └── main.parameters.json
├── deploy.ps1              # Deployment script
├── Dockerfile              # Container definition
├── docker-compose.yml      # Container orchestration
├── requirements.txt        # Python dependencies
├── FOUNDRY_SETUP.md        # Azure AI Foundry setup guide
├── .env.example            # Environment variable template
└── README.md               # This file
```

## Limitations

1. **Website Accuracy**: May not always find the correct official website for smaller hotels
2. **Room Data Availability**: Not all hotel websites list room counts
3. **Rate Limiting**: External APIs (Bing Grounding, scraping) have rate limits
4. **Processing Time**: Each lookup takes 5-15 seconds; batch processing uses parallel execution
5. **Model Constraint**: Only `gpt-4.1-mini` works reliably with Bing Grounding tools

## Improvements for Production

1. ~~**Add Redis caching** to avoid re-scraping recent lookups~~ Done
2. ~~**Add Playwright/Selenium** for JavaScript-rendered sites~~ Done
3. **Add retry queues** for failed lookups
4. **Add webhook support** for async batch processing
5. **Add authentication** (API keys, OAuth)
6. **Add managed identity** for Container App to access AI Foundry without API keys

## License

MIT
