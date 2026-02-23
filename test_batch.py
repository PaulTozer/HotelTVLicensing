import requests, json, time, sys

API_BASE = "http://127.0.0.1:8000"
BATCH_URL = f"{API_BASE}/api/v1/hotel/batch"
SINGLE_URL = f"{API_BASE}/api/v1/hotel/lookup"

hotels = [
    {"name": "Aparthotel", "address": "8 Osborne Road", "city": "Blackpool", "postcode": "FY4 1HJ"},
    {"name": "Lynwood Hotel", "address": "38 Osborne Road", "city": "Blackpool", "postcode": "FY4 1HQ"},
    {"name": "The Colwyn Hotel", "address": "569 New South Promenade", "city": "Blackpool", "postcode": "FY4 1NG"},
    {"name": "Clifton Court Hotel", "address": "12 Clifton Drive", "city": "Blackpool", "postcode": "FY4 1NX"},
    {"name": "Mode Hotel", "address": "1 Clifton Square", "city": "Lytham St. Annes", "postcode": "FY8 5JP"},
    {"name": "Clifton Hotel", "address": "26-27 Buckingham Terrace", "city": "Glasgow", "postcode": "G12 8ED"},
    {"name": "Culcreuch Castle Hotel", "address": "Kippen Road, Fintry", "city": "Glasgow", "postcode": "G63 0LW"},
    {"name": "Uplawmoor Hotel", "address": "66 Neilston Road, Uplawmoor", "city": "Glasgow", "postcode": "G78 4AF"},
    {"name": "Duck Bay Hotel & Cottages", "address": "Alexandria", "city": "Alexandria", "postcode": "G83 8QZ"},
    {"name": "The County Hotel", "address": "Old Luss Road", "city": "Helensburgh", "postcode": "G84 7BH"},
    {"name": "Wayside Cheer Hotel", "address": "Les Grandes Rocques, Castel", "city": "Guernsey", "postcode": "GY5 7FX"},
    {"name": "Hindes Hotel", "address": "6-8 Hindes Road", "city": "Harrow", "postcode": "HA1 1SJ"},
    {"name": "Garden Court Hotel", "address": "Watermead", "city": "Aylesbury", "postcode": "HP19 0FY"},
    {"name": "The Bridge House Hotel", "address": "Wilton", "city": "Ross-on-Wye", "postcode": "HR9 6AA"},
    {"name": "Loch Erisort Hotel", "address": "Shieldinish", "city": "Isle of Lewis", "postcode": "HS2 9RA"},
    {"name": "Hamersay Hotel", "address": "Lochmaddy", "city": "Isle of North Uist", "postcode": "HS6 5AE"},
    {"name": "Pier Hotel", "address": "9 Seaside Road", "city": "Withernsea", "postcode": "HU19 2DL"},
    {"name": "Alexandra Hotel", "address": "90 Queen Street", "city": "Withernsea", "postcode": "HU19 2HB"},
    {"name": "Vale Apart Hotel", "address": "6 Coltman Street", "city": "Hull", "postcode": "HU3 2SG"},
    {"name": "White Lion Hotel", "address": "Bridge Gate", "city": "Hebden Bridge", "postcode": "HX7 8EX"},
    {"name": "Cranford Hotel", "address": "22-26 Argyle Road", "city": "Ilford", "postcode": "IG1 3BQ"},
    {"name": "Mayfair Hotel", "address": "13 Balfour Road", "city": "Ilford", "postcode": "IG1 4HP"},
    {"name": "Rossmore Hotel", "address": "301-309 Cranbrook Road", "city": "Ilford", "postcode": "IG1 4UA"},
    {"name": "Trevelyan Hotel", "address": "18-19 Palace Terrace", "city": "Douglas, Isle of Man", "postcode": "IM2 4NE"},
    {"name": "Glen Mona Hotel", "address": "Glen Mona, Ramsey", "city": "Isle of Man", "postcode": "IM7 1HF"},
]

mode = sys.argv[1] if len(sys.argv) > 1 else "batch"
fast = "--fast" in sys.argv

if mode == "batch":
    label = "FAST BATCH" if fast else "BATCH"
    print(f"=== {label} MODE: {len(hotels)} hotels ===")
    url = f"{BATCH_URL}?fast=true" if fast else BATCH_URL
    print(f"Sending batch request to {url}...")
    start = time.time()
    
    try:
        r = requests.post(BATCH_URL, json={"hotels": hotels}, timeout=600)
        elapsed = time.time() - start
        
        if r.status_code != 200:
            print(f"ERROR: HTTP {r.status_code}: {r.text[:500]}")
            sys.exit(1)
        
        data = r.json()
        
        print(f"\n{'#':<3} {'Hotel':<30} {'Status':<10} {'Rooms':<12} {'Phone':<20} {'Website':<45} {'Conf':<5}")
        print("-" * 125)
        
        for i, d in enumerate(data.get("results", []), 1):
            rmin = d.get('rooms_min')
            rmax = d.get('rooms_max')
            rooms = f"{rmin if rmin is not None else '?'}-{rmax if rmax is not None else '?'}"
            name = str(d.get('search_name') or '?')[:29]
            status = str(d.get('status') or '?')
            phone = str(d.get('uk_contact_phone') or 'N/A')[:19]
            website = str(d.get('official_website') or 'N/A')[:44]
            conf = d.get('confidence_score')
            conf_str = str(conf) if conf is not None else '?'
            print(f"{i:<3} {name:<30} {status:<10} {rooms:<12} {phone:<20} {website:<45} {conf_str:<5}")
        
        print("-" * 125)
        print(f"\nSummary:")
        print(f"  Total:      {data.get('total_requested', '?')}")
        print(f"  Successful: {data.get('successful', '?')}")
        print(f"  Partial:    {data.get('partial', '?')}")
        print(f"  Failed:     {data.get('failed', '?')}")
        print(f"  Server time: {data.get('processing_time_seconds', '?')}s")
        print(f"  Total time:  {elapsed:.1f}s (includes network)")
        rate = len(hotels) / elapsed if elapsed > 0 else 0
        print(f"  Throughput:  {rate:.1f} hotels/sec")
        
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

elif mode == "sequential":
    print(f"=== SEQUENTIAL MODE: {len(hotels)} hotels (for comparison) ===")
    start = time.time()
    
    print(f"\n{'#':<3} {'Hotel':<30} {'Status':<10} {'Rooms':<12} {'Phone':<20} {'Time':<8}")
    print("-" * 90)
    
    for i, h in enumerate(hotels, 1):
        t0 = time.time()
        try:
            r = requests.post(SINGLE_URL, json=h, timeout=120)
            d = r.json()
            t1 = time.time()
            rmin = d.get('rooms_min')
            rmax = d.get('rooms_max')
            rooms = f"{rmin if rmin is not None else '?'}-{rmax if rmax is not None else '?'}"
            name = str(d.get('search_name') or h['name'])[:29]
            status = str(d.get('status') or '?')
            phone = str(d.get('uk_contact_phone') or 'N/A')[:19]
            print(f"{i:<3} {name:<30} {status:<10} {rooms:<12} {phone:<20} {t1-t0:.1f}s")
        except Exception as e:
            t1 = time.time()
            print(f"{i:<3} {h['name'][:29]:<30} {'ERROR':<10} {'-':<12} {'-':<20} {t1-t0:.1f}s")
    
    elapsed = time.time() - start
    print("-" * 90)
    print(f"Total: {elapsed:.1f}s | {len(hotels)/elapsed:.2f} hotels/sec")

else:
    print(f"Usage: python test_batch.py [batch|sequential] [--fast]")
    print(f"  batch           - Use batch endpoint (parallel, default)")
    print(f"  batch --fast    - Batch with fast mode (Bing only, no deep scraping)")
    print(f"  sequential      - Call single endpoint one at a time (for comparison)")
