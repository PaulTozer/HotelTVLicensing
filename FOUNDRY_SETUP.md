# Azure AI Foundry Agent Setup Guide
## Hotel TV Licensing Agent

This guide will help you set up an AI agent in Azure AI Foundry that uses your Hotel API to process hotel spreadsheets.

---

## Prerequisites

✅ You have an Azure AI Foundry project  
✅ You have the Hotel API deployed at:  
   `https://<your-app-name>.azurecontainerapps.io`

---

## Step 1: Open Azure AI Foundry Portal

1. Go to **https://ai.azure.com** 
2. Click on **"Preview portal"** if you're not already in the new portal
3. Select your project

---

## Step 2: Create a New Agent

1. In the left sidebar, click **"Agents"** (under Build section)
2. Click **"+ New agent"** or **"Create agent"**
3. Give your agent a name: `HotelTVLicensingAgent`

---

## Step 3: Configure Agent Instructions

Copy and paste these instructions into the **Instructions** field:

```
You are a Hotel TV Licensing assistant. Your job is to help process lists of hotels and gather information about them using the hotel_lookup_api tool.

When the user provides a list of hotels (from a file or directly in chat):

1. For EACH hotel, call the lookupHotelInformation operation with:
   - name: The hotel name
   - address: The hotel address (city, street)

2. Present results in a table format:
   | Hotel Name | Address | Rooms | Website | Phone | Status |

3. After processing, provide a summary:
   - Total hotels processed
   - Successful lookups
   - Any failures

4. If asked to create a spreadsheet/CSV output, format as:
   Hotel Name,Address,Rooms Min,Rooms Max,Official Website,UK Contact Phone,Rooms Source Notes,Status,Confidence Score

CRITICAL - BATCH SIZE LIMITS:
- Process hotels in batches of 5-10 maximum
- If the user provides more than 10 hotels, split into smaller batches
- Wait for each batch to complete before starting the next
- Between batches, tell the user progress (e.g., "Completed 10 of 30 hotels...")
- Each lookup takes ~10-15 seconds due to web scraping and AI analysis
- Processing 10 hotels will take approximately 2-3 minutes

IMPORTANT: 
- Process hotels ONE AT A TIME (the API includes rate limiting delays)
- Always include the confidence score in your summary
- If a lookup fails, note it and continue to the next hotel
- If you see multiple failures in a row, slow down and wait longer between calls
```

---

## Step 4: Add the OpenAPI Tool

1. Scroll down to the **Tools** section
2. Click **"+ Add tool"**
3. Select **"OpenAPI"** (or "Custom API")
4. Configure the tool:

   - **Name**: `hotel_lookup_api`
   - **Description**: `API to look up hotel information including room counts, websites, and phone numbers`
   - **Authentication**: Select **"Anonymous"** (no authentication required)

5. For the **OpenAPI Schema**, paste the following JSON:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Hotel TV Licensing API",
    "description": "API to look up hotel information including room counts, official websites, and contact phone numbers.",
    "version": "1.0.0"
  },
  "servers": [
    {
      "url": "https://<your-app-name>.<unique-id>.swedencentral.azurecontainerapps.io"
    }
  ],
  "paths": {
    "/api/v1/hotel/lookup": {
      "post": {
        "operationId": "lookupHotelInformation",
        "summary": "Look up hotel information",
        "description": "Searches for a hotel's official website, UK contact phone number, and room count using AI-powered web scraping.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["name"],
                "properties": {
                  "name": {
                    "type": "string",
                    "description": "The name of the hotel to look up"
                  },
                  "address": {
                    "type": "string",
                    "description": "The address of the hotel for disambiguation"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Hotel information retrieved",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "search_name": { "type": "string" },
                    "official_website": { "type": "string" },
                    "uk_contact_phone": { "type": "string" },
                    "rooms_min": { "type": "integer" },
                    "rooms_max": { "type": "integer" },
                    "rooms_source_notes": { "type": "string" },
                    "status": { "type": "string" },
                    "confidence_score": { "type": "number" }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

6. Click **"Save"** or **"Add tool"**

---

## Step 5: Add File Search Capability (for spreadsheet knowledge)

1. In the **Tools** section, also add **"File Search"** if available
2. This allows the agent to read uploaded spreadsheets

---

## Step 6: Save and Test

1. Click **"Save"** or **"Create"** to save your agent
2. Click **"Test in playground"** or **"Try it"**
3. Upload your hotel spreadsheet (CSV or Excel)
4. Send a message like:

   ```
   Process the hotels in the uploaded file and create a CSV with all their information
   ```

---

## Sample Test Prompts

Try these prompts to test your agent:

**Single hotel lookup:**
```
Look up information for The Savoy hotel in London
```

**Process a list:**
```
Look up information for these hotels:
1. The Savoy, Strand, London
2. The Grand Hotel, Kings Road, Brighton
3. The Dorchester, Park Lane, London
```

**Create output spreadsheet:**
```
Process all hotels and output the results as a CSV that I can paste into Excel
```

---

## Sample Hotel List (CSV)

Here's a sample CSV you can upload to test:

```csv
Hotel Name,Address,City,Postcode
The Savoy,Strand,London,WC2R 0EZ
The Grand Hotel,Kings Road,Brighton,BN1 2FW
The Dorchester,Park Lane,London,W1K 1QA
The Ritz London,150 Piccadilly,London,W1J 9BR
Claridge's,Brook Street,London,W1K 4HR
```

---

## Expected Output Format

The agent will output results like this:

| Hotel Name | Address | Rooms | Website | Phone | Status |
|------------|---------|-------|---------|-------|--------|
| The Savoy | Strand, London | 263 | https://thesavoylondon.com/ | +44 (0)20 7836 4343 | success |
| The Grand Hotel | Brighton | 205 | https://www.grandbrighton.co.uk | +44 1273 224300 | success |

---

## Troubleshooting

**Agent doesn't call the API:**
- Make sure the OpenAPI tool is saved and enabled
- Check that "Anonymous" authentication is selected
- Verify the server URL is correct

**API timeout errors:**
- The API can take 20-30 seconds per hotel
- Process fewer hotels at a time
- Try again - some lookups fail intermittently

**No results found:**
- The hotel name might be too common or ambiguous
- Try adding more specific address details
- Check the API is running: visit `/health` endpoint

---

## Files in Your Project

- `openapi.json` - Full OpenAPI specification for the Hotel API
- `sample_hotels.csv` - Sample hotel list to test with
- `foundry_agent.py` - Python script for programmatic agent creation
- `FOUNDRY_SETUP.md` - This setup guide

---

## API Endpoint Reference

- **Base URL**: `https://<your-app-name>.<unique-id>.swedencentral.azurecontainerapps.io`
- **Single Lookup**: `POST /api/v1/hotel/lookup`
- **Batch Lookup**: `POST /api/v1/hotel/batch`
- **Health Check**: `GET /health`
