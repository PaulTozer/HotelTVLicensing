"""
Azure AI Foundry Agent for Hotel TV Licensing

This script creates an agent in Azure AI Foundry that:
1. Uses the Hotel API as an OpenAPI tool
2. Can read hotel lists and process them
3. Outputs enriched hotel data

Prerequisites:
- pip install azure-ai-projects azure-identity python-dotenv
- Set environment variables in .env file
"""

import os
import sys
import json
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

# Configuration
PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
if not PROJECT_ENDPOINT:
    print("ERROR: Set AZURE_AI_PROJECT_ENDPOINT in your .env file")
    print("Example: https://your-foundry.services.ai.azure.com/api/projects/yourproject")
    sys.exit(1)
MODEL_DEPLOYMENT = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4")

# Load OpenAPI spec
def load_openapi_spec():
    spec_path = os.path.join(os.path.dirname(__file__), "openapi.json")
    with open(spec_path, "r") as f:
        return json.load(f)

# Create the Hotel API tool
def create_hotel_api_tool():
    """Create the OpenAPI tool definition for the Hotel API"""
    spec = load_openapi_spec()
    
    return {
        "type": "openapi",
        "openapi": {
            "name": "hotel_lookup_api",
            "description": "API to look up hotel information including room counts, websites, and phone numbers",
            "spec": spec,
            "auth": {
                "type": "anonymous"  # Our API doesn't require authentication
            }
        }
    }

# Agent instructions
AGENT_INSTRUCTIONS = """You are a Hotel TV Licensing assistant. Your job is to help process lists of hotels and gather information about them.

When the user provides a list of hotels (either directly or from an uploaded file), you should:

1. For each hotel in the list, use the hotel_lookup_api tool to look up:
   - Official website
   - UK contact phone number
   - Number of rooms (min and max)
   - Source notes and confidence scores

2. Present the results in a clear, tabular format showing:
   - Hotel Name
   - Address
   - Rooms (Min-Max)
   - Official Website
   - UK Contact Phone
   - Status
   - Confidence Score

3. After processing all hotels, provide a summary:
   - Total hotels processed
   - Successful lookups
   - Failed/partial lookups
   - Any common issues encountered

4. If asked to create a spreadsheet, format the output as CSV that can be copied and pasted into Excel.

Important notes:
- Process hotels one at a time to ensure accuracy
- If a lookup fails, note the error and continue with the next hotel
- Always include the source notes so users know where the information came from
- Be prepared to re-try lookups if they fail initially

When outputting as CSV, use these columns:
Hotel Name,Address,Rooms Min,Rooms Max,Official Website,UK Contact Phone,Rooms Source Notes,Website Source URL,Phone Source URL,Status,Last Checked,Confidence Score
"""


def main():
    """Main function to create and demonstrate the agent"""
    print("=" * 60)
    print("Azure AI Foundry - Hotel TV Licensing Agent Setup")
    print("=" * 60)
    
    # Check if we can connect
    print(f"\nProject Endpoint: {PROJECT_ENDPOINT}")
    print(f"Model Deployment: {MODEL_DEPLOYMENT}")
    
    try:
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
        
        print("\n✓ Successfully connected to Azure AI Foundry")
        
        # Create the tool
        hotel_tool = create_hotel_api_tool()
        print("✓ Hotel API tool definition created")
        
        # Create the agent
        print("\nCreating agent...")
        agent = project_client.agents.create_version(
            agent_name="HotelTVLicensingAgent",
            definition={
                "model": MODEL_DEPLOYMENT,
                "instructions": AGENT_INSTRUCTIONS,
                "tools": [hotel_tool],
            },
            description="Agent for processing hotel lists and gathering TV licensing information",
        )
        
        print(f"✓ Agent created successfully!")
        print(f"  - Agent ID: {agent.id}")
        print(f"  - Agent Name: {agent.name}")
        print(f"  - Version: {agent.version}")
        
        print("\n" + "=" * 60)
        print("NEXT STEPS:")
        print("=" * 60)
        print("""
1. Go to https://ai.azure.com and open your project
2. Navigate to Agents in the left sidebar
3. You should see 'HotelTVLicensingAgent' listed
4. Click on it to open the playground
5. Upload your hotel spreadsheet as a file attachment
6. Ask the agent to process the hotels

Example prompts:
- "Process the hotels in the uploaded file and create a CSV with all their information"
- "Look up information for The Savoy hotel in London"
- "Create a spreadsheet with room counts for all hotels listed"
""")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTo create the agent manually in the portal, follow these steps:")
        print_manual_instructions()


def print_manual_instructions():
    """Print instructions for manual setup in the portal"""
    print("""
================================================================================
MANUAL SETUP INSTRUCTIONS FOR AZURE AI FOUNDRY PORTAL
================================================================================

1. GO TO THE FOUNDRY PORTAL:
   https://ai.azure.com
   
2. OPEN YOUR PROJECT:
   - Select your project from the projects list

3. CREATE A NEW AGENT:
   - Click on "Agents" in the left sidebar (or "Build" > "Agents")
   - Click "+ Create agent" or "New agent"
   
4. CONFIGURE THE AGENT:
   Name: HotelTVLicensingAgent
   Model: gpt-5.2-chat (or your deployed model)
   
5. SET THE INSTRUCTIONS:
   Copy and paste the following instructions:
   
---BEGIN INSTRUCTIONS---
You are a Hotel TV Licensing assistant. Your job is to help process lists of hotels and gather information about them.

When the user provides a list of hotels (either directly or from an uploaded file), you should:

1. For each hotel in the list, use the hotel_lookup_api tool to look up:
   - Official website
   - UK contact phone number  
   - Number of rooms (min and max)
   - Source notes and confidence scores

2. Present the results in a clear, tabular format showing:
   - Hotel Name
   - Address
   - Rooms (Min-Max)
   - Official Website
   - UK Contact Phone
   - Status
   - Confidence Score

3. After processing all hotels, provide a summary.

4. If asked to create a spreadsheet, format the output as CSV.

When outputting as CSV, use these columns:
Hotel Name,Address,Rooms Min,Rooms Max,Official Website,UK Contact Phone,Rooms Source Notes,Website Source URL,Phone Source URL,Status,Last Checked,Confidence Score
---END INSTRUCTIONS---

6. ADD THE OPENAPI TOOL:
   - Click "Add tool" or "Tools" section
   - Select "OpenAPI" or "Custom API"
   - Name: hotel_lookup_api
   - Authentication: Anonymous (None)
   - Paste the OpenAPI schema from: openapi.json in your project folder
   
7. SAVE THE AGENT

8. TEST IN PLAYGROUND:
   - Upload your hotel spreadsheet
   - Type: "Process the hotels in the uploaded file"

================================================================================
""")


if __name__ == "__main__":
    main()
