"""
Azure AI Foundry - HotelTVSearch Agent Setup

Creates the HotelTVSearch agent in Azure AI Foundry that uses Bing Grounding
to search for hotel information (official websites, phone numbers, room counts).

This agent uses Bing Grounding,
providing a more integrated Azure-native solution.

Prerequisites:
- pip install azure-ai-projects azure-identity python-dotenv
- Azure AI Foundry project with Bing Grounding connection configured
- Set environment variables in .env file

Usage:
    python foundry_search_agent.py
"""

import os
import json
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import BingGroundingTool

load_dotenv()

# Configuration
PROJECT_ENDPOINT = os.getenv(
    "AZURE_AI_PROJECT_ENDPOINT",
    "https://PT-AzureAIFoundry-SweCent.services.ai.azure.com/api/projects/firstproject",
)
MODEL_DEPLOYMENT = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
BING_CONNECTION_NAME = os.getenv("BING_CONNECTION_NAME", "PTGroundingBingSearchectup5")

# Agent instructions for HotelTVSearch
AGENT_INSTRUCTIONS = """You are a hotel information research assistant called HotelTVSearch. 
Your job is to search the web to find accurate information about UK hotels.

When given a hotel name (and optionally an address/city), you must search for and return:

1. **Official Website**: The hotel's own website URL (NOT booking sites like booking.com, expedia, hotels.com, tripadvisor, agoda, kayak, trivago)
2. **UK Contact Phone**: The hotel's direct UK phone number (starting with +44, 01, 02, 03, or 0800)
3. **Room Count**: The total number of guest rooms/bedrooms

IMPORTANT RULES:
- Search specifically using Bing to find the hotel
- Always prioritise the hotel's OWN official website over aggregator/booking sites
- For phone numbers, prefer landline (01, 02, 03) over mobile (07)
- For room counts, look for phrases like "X rooms", "X bedrooms", "X guest rooms"
- If you find a range (e.g., "150-200 rooms"), provide both min and max
- Only include information you are confident about
- If you cannot find a piece of information, set it to null

You MUST respond with ONLY valid JSON in this exact format (no markdown, no explanation, just JSON):
{
    "official_website": "<URL or null>",
    "uk_contact_phone": "<phone number or null>",
    "rooms_min": <number or null>,
    "rooms_max": <number or null>,
    "rooms_source_notes": "<brief note about where you found room info, or null>",
    "hotel_name_found": "<the exact hotel name as found online>",
    "address_found": "<the address if found, or null>",
    "confidence": <0.0 to 1.0>,
    "search_sources": ["<list of URLs used as sources>"]
}
"""


def main():
    """Create and test the HotelTVSearch agent"""
    print("=" * 60)
    print("Azure AI Foundry - HotelTVSearch Agent Setup")
    print("(Bing Grounding)")
    print("=" * 60)

    print(f"\nProject Endpoint: {PROJECT_ENDPOINT}")
    print(f"Model Deployment: {MODEL_DEPLOYMENT}")
    print(f"Bing Connection:  {BING_CONNECTION_NAME}")

    try:
        credential = DefaultAzureCredential()
        client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
        print("\n✓ Connected to Azure AI Foundry")

        # Get the Bing connection
        bing_connection = client.connections.get(BING_CONNECTION_NAME)
        print(f"✓ Found Bing connection: {bing_connection.id}")

        # Create the Bing grounding tool
        bing_tool = BingGroundingTool(
            connection_id=bing_connection.id,
            market="en-GB",
            count=10,
        )
        print("✓ Bing grounding tool created")

        # Check for existing agents with the same name
        existing_agents = client.agents.list_agents()
        for agent in existing_agents:
            if agent.name == "HotelTVSearch":
                print(f"\n⚠ Found existing HotelTVSearch agent: {agent.id}")
                response = input("Delete and recreate? (y/n): ").strip().lower()
                if response == "y":
                    client.agents.delete_agent(agent.id)
                    print(f"  Deleted agent {agent.id}")
                else:
                    print("  Keeping existing agent")
                    return

        # Create the agent
        print("\nCreating HotelTVSearch agent...")
        agent = client.agents.create_agent(
            model=MODEL_DEPLOYMENT,
            name="HotelTVSearch",
            description="Searches for hotel information (website, phone, rooms) using Bing grounding.",
            instructions=AGENT_INSTRUCTIONS,
            tools=bing_tool.definitions,
        )

        print(f"✓ Agent created successfully!")
        print(f"  - Agent ID: {agent.id}")
        print(f"  - Agent Name: {agent.name}")
        print(f"  - Model: {MODEL_DEPLOYMENT}")

        # Test the agent
        print("\n" + "-" * 60)
        test = input("Test the agent with a sample hotel? (y/n): ").strip().lower()
        if test == "y":
            test_hotel = input("Hotel name (default: 'The Ritz London'): ").strip()
            if not test_hotel:
                test_hotel = "The Ritz London"

            print(f"\n🔍 Searching for: {test_hotel}")

            from azure.ai.agents.models import AgentThreadCreationOptions, ThreadMessageOptions

            run = client.agents.create_thread_and_process_run(
                agent_id=agent.id,
                thread=AgentThreadCreationOptions(
                    messages=[
                        ThreadMessageOptions(
                            role="user",
                            content=f'Find information about the hotel: "{test_hotel}"\nLocation: London, UK\n\nSearch for the hotel\'s official website, UK phone number, and room count. Return ONLY the JSON response as specified in your instructions.',
                        )
                    ]
                ),
            )

            print(f"  Run status: {run.status}")

            if run.status == "completed":
                messages = client.agents.messages.list(thread_id=run.thread_id)
                for msg in messages:
                    if msg.role == "assistant":
                        for content_block in msg.content:
                            if hasattr(content_block, "text"):
                                response_text = content_block.text.value
                                print(f"\n  Agent Response:")
                                print(f"  {response_text}")

                                # Try to parse as JSON
                                try:
                                    text = response_text.strip()
                                    if text.startswith("```json"):
                                        text = text[7:]
                                    if text.startswith("```"):
                                        text = text[3:]
                                    if text.endswith("```"):
                                        text = text[:-3]
                                    result = json.loads(text.strip())
                                    print(f"\n  ✓ Parsed JSON successfully:")
                                    print(f"    Website: {result.get('official_website')}")
                                    print(f"    Phone:   {result.get('uk_contact_phone')}")
                                    print(f"    Rooms:   {result.get('rooms_min')}-{result.get('rooms_max')}")
                                    print(f"    Confidence: {result.get('confidence')}")
                                except json.JSONDecodeError:
                                    print("  ⚠ Response was not valid JSON")
                        break
            else:
                print(f"  ❌ Run failed: {run.status}")
                if hasattr(run, "last_error") and run.last_error:
                    print(f"  Error: {run.last_error}")

        # Cleanup option
        print("\n" + "-" * 60)
        cleanup = input("Delete the test agent? (y/n): ").strip().lower()
        if cleanup == "y":
            client.agents.delete_agent(agent.id)
            print("✓ Agent deleted")
        else:
            print(f"Agent ID kept: {agent.id}")

        print("\n" + "=" * 60)
        print("NEXT STEPS:")
        print("=" * 60)
        print(f"""
The HotelTVSearch agent uses Bing Grounding for web search.

To use it in the API:
1. Set these environment variables:
   AZURE_AI_PROJECT_ENDPOINT={PROJECT_ENDPOINT}
   BING_CONNECTION_NAME={BING_CONNECTION_NAME}
   AZURE_AI_MODEL_DEPLOYMENT_NAME={MODEL_DEPLOYMENT}

2. The API will automatically use Bing grounding for hotel searches

Architecture:
  Bing Grounding Agent → Web Scrape (optional) → AI Extract
""")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
