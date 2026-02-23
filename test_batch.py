import requests, json

API = "http://127.0.0.1:8000/api/v1/hotel/lookup"

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

print(f"{'#':<3} {'Hotel':<30} {'Status':<10} {'Rooms':<12} {'Phone':<20} {'Website':<45} {'Conf':<5}")
print("-" * 125)

for i, h in enumerate(hotels, 1):
    try:
        r = requests.post(API, json=h, timeout=120)
        d = r.json()
        rooms = f"{d.get('rooms_min','?')}-{d.get('rooms_max','?')}"
        print(f"{i:<3} {d.get('search_name','?')[:29]:<30} {d.get('status','?'):<10} {rooms:<12} {(d.get('uk_contact_phone') or 'N/A')[:19]:<20} {(d.get('official_website') or 'N/A')[:44]:<45} {d.get('confidence_score','?'):<5}")
    except Exception as e:
        print(f"{i:<3} {h['name'][:29]:<30} ERROR      -            -                    -                                             -")
        print(f"    Error: {e}")

print("-" * 125)
print("Done!")
