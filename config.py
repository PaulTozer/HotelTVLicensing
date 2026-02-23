"""Configuration settings for the Hotel Info API"""

import os
from dotenv import load_dotenv

load_dotenv()

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
AZURE_OPENAI_FALLBACK_DEPLOYMENT = os.getenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "gpt-4.1-mini")

# Azure AI Foundry Configuration (for Bing Grounding agent)
AZURE_AI_PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
AZURE_AI_MODEL_DEPLOYMENT = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
BING_CONNECTION_NAME = os.getenv("BING_CONNECTION_NAME")
USE_BING_GROUNDING = os.getenv("USE_BING_GROUNDING", "true").lower() == "true"

# Redis Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() == "true"
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))

# Determine which AI provider to use
USE_AZURE_OPENAI = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)

# Rate limiting
MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "60"))
SCRAPE_TIMEOUT_SECONDS = int(os.getenv("SCRAPE_TIMEOUT_SECONDS", "30"))

# Retry settings
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "3"))
AI_RETRY_DELAY_BASE = float(os.getenv("AI_RETRY_DELAY_BASE", "2.0"))

# Batch processing
BATCH_MAX_CONCURRENT = int(os.getenv("BATCH_MAX_CONCURRENT", "25"))
BATCH_MAX_SIZE = int(os.getenv("BATCH_MAX_SIZE", "500"))

# Retry queue
RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BACKOFF_BASE = float(os.getenv("RETRY_BACKOFF_BASE", "30.0"))
RETRY_MAX_CONCURRENT = int(os.getenv("RETRY_MAX_CONCURRENT", "5"))
RETRY_AUTO_ENQUEUE = os.getenv("RETRY_AUTO_ENQUEUE", "true").lower() == "true"
BING_MAX_CONCURRENT = int(os.getenv("BING_MAX_CONCURRENT", "15"))
BING_THREAD_POOL_SIZE = int(os.getenv("BING_THREAD_POOL_SIZE", "20"))
BING_RETRY_MAX = int(os.getenv("BING_RETRY_MAX", "3"))
BING_RETRY_DELAY_BASE = float(os.getenv("BING_RETRY_DELAY_BASE", "2.0"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# User agent for web scraping
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Common UK phone prefixes
UK_PHONE_PREFIXES = ["+44", "0044", "44", "01onal", "02", "03", "07", "08"]
