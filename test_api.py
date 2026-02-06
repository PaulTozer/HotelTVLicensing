"""
Test script for the Hotel Information API

Run this after setting your OPENAI_API_KEY in .env
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8000"


def test_health():
    """Test the health endpoint"""
    print("Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print()


def test_single_lookup(name: str, city: str = None, address: str = None, postcode: str = None):
    """Test a single hotel lookup"""
    print(f"Looking up: {name}")
    print("-" * 50)
    
    payload = {"name": name}
    if city:
        payload["city"] = city
    if address:
        payload["address"] = address
    if postcode:
        payload["postcode"] = postcode
    
    response = requests.post(
        f"{BASE_URL}/api/v1/hotel/lookup",
        json=payload,
        timeout=120  # 2 minute timeout for scraping
    )
    
    result = response.json()
    print(f"Status: {result['status']}")
    print(f"Website: {result.get('official_website')}")
    print(f"Phone: {result.get('uk_contact_phone')}")
    print(f"Rooms: {result.get('rooms_min')} - {result.get('rooms_max')}")
    print(f"Rooms Source: {result.get('rooms_source_notes')}")
    print(f"Confidence: {result.get('confidence_score')}")
    if result.get('errors'):
        print(f"Errors: {result['errors']}")
    print()
    
    return result


def test_batch_lookup():
    """Test batch hotel lookup"""
    print("Testing batch lookup...")
    print("-" * 50)
    
    hotels = [
        {"name": "The Grand Hotel Brighton", "city": "Brighton"},
        {"name": "The Ritz London", "city": "London"},
        {"name": "Premier Inn Manchester City Centre", "city": "Manchester"},
    ]
    
    response = requests.post(
        f"{BASE_URL}/api/v1/hotel/batch",
        json={"hotels": hotels},
        timeout=300  # 5 minutes for batch
    )
    
    result = response.json()
    print(f"Total: {result['total_requested']}")
    print(f"Successful: {result['successful']}")
    print(f"Partial: {result['partial']}")
    print(f"Failed: {result['failed']}")
    print()
    
    for hotel_result in result['results']:
        print(f"  {hotel_result['search_name']}: {hotel_result['status']}")
        if hotel_result.get('rooms_min'):
            print(f"    Rooms: {hotel_result['rooms_min']}")
    
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("Hotel Information API - Test Script")
    print("=" * 60)
    print()
    
    # Test health
    test_health()
    
    # Test single lookups
    test_single_lookup("The Grand Hotel Brighton", city="Brighton")
    test_single_lookup("The Savoy", city="London")
    test_single_lookup("Gleneagles Hotel", city="Perthshire")
    
    # Uncomment to test batch
    # test_batch_lookup()
