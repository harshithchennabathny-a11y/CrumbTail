"""
Bangalore (Bengaluru) Seed Data for CrumbTail Live Demo.
NOTE: demo data, approximate locations.
"""
from typing import List, Dict, Any, Tuple

# 15 realistic restaurants across major Bengaluru localities with busyness weights
BANGALORE_RESTAURANTS: List[Dict[str, Any]] = [
    {
        "id": "rest_meghana_koramangala",
        "name": "Meghana Foods (Biryani & Andhra)",
        "locality": "Koramangala",
        "lat": 12.9352,
        "lon": 77.6245,
        "weight": 12,  # Hotspot: high order volume for batching demo
        "tags": ["biryani", "andhra", "hotspot"]
    },
    {
        "id": "rest_toit_indiranagar",
        "name": "Toit Brewpub & Kitchen",
        "locality": "Indiranagar",
        "lat": 12.9784,
        "lon": 77.6408,
        "weight": 10,  # Hotspot
        "tags": ["continental", "pizza", "hotspot"]
    },
    {
        "id": "rest_empire_mgroad",
        "name": "Hotel Empire (Late Night)",
        "locality": "MG Road",
        "lat": 12.9757,
        "lon": 77.6068,
        "weight": 9,
        "tags": ["shawarma", "kebab", "indian"]
    },
    {
        "id": "rest_vidyarthi_malleshwaram",
        "name": "Vidyarthi Bhavan Heritage",
        "locality": "Malleshwaram",
        "lat": 13.0035,
        "lon": 77.5710,
        "weight": 8,
        "tags": ["dosa", "south_indian", "coffee"]
    },
    {
        "id": "rest_hsr_darshini",
        "name": "HSR Udupi Park Darshini",
        "locality": "HSR Layout",
        "lat": 12.9116,
        "lon": 77.6389,
        "weight": 8,
        "tags": ["breakfast", "south_indian"]
    },
    {
        "id": "rest_babu_btm",
        "name": "Babu Biryani Point",
        "locality": "BTM",
        "lat": 12.9166,
        "lon": 77.6101,
        "weight": 8,
        "tags": ["biryani", "rolls"]
    },
    {
        "id": "rest_jayanagar_kamat",
        "name": "Kamat Bugle Rock Heritage",
        "locality": "Basavanagudi",
        "lat": 12.9406,
        "lon": 77.5738,
        "weight": 7,
        "tags": ["thali", "north_karnataka"]
    },
    {
        "id": "rest_jayanagar_tiffin",
        "name": "Maiyas Jayanagar 4th Block",
        "locality": "Jayanagar",
        "lat": 12.9308,
        "lon": 77.5838,
        "weight": 7,
        "tags": ["sweets", "chaat", "coffee"]
    },
    {
        "id": "rest_jpnagar_bbq",
        "name": "The Black Pearl Pirate Grill",
        "locality": "JP Nagar",
        "lat": 12.9063,
        "lon": 77.5857,
        "weight": 6,
        "tags": ["bbq", "buffet"]
    },
    {
        "id": "rest_marathahalli_punjabi",
        "name": "Punjabi Rasoi Marathahalli",
        "locality": "Marathahalli",
        "lat": 12.9569,
        "lon": 77.7011,
        "weight": 7,
        "tags": ["north_indian", "curry"]
    },
    {
        "id": "rest_whitefield_windmills",
        "name": "Windmills Craftworks Dining",
        "locality": "Whitefield",
        "lat": 12.9698,
        "lon": 77.7500,
        "weight": 6,
        "tags": ["burgers", "artisan"]
    },
    {
        "id": "rest_hebbal_sheroes",
        "name": "Hebbal Lake Bistro",
        "locality": "Hebbal",
        "lat": 13.0358,
        "lon": 77.5970,
        "weight": 5,
        "tags": ["pan_asian", "cafe"]
    },
    {
        "id": "rest_ecity_bawarchi",
        "name": "Electronics City Bawarchi Hub",
        "locality": "Electronic City",
        "lat": 12.8452,
        "lon": 77.6602,
        "weight": 6,
        "tags": ["hyderabadi", "biryani"]
    },
    {
        "id": "rest_koramangala_truffles",
        "name": "Truffles Ice & Spice Burgers",
        "locality": "Koramangala",
        "lat": 12.9340,
        "lon": 77.6210,
        "weight": 11,  # Hotspot: burger surges for batch dropoffs
        "tags": ["burgers", "pasta", "hotspot"]
    },
    {
        "id": "rest_indiranagar_rameshwaram",
        "name": "The Rameshwaram Cafe Indiranagar",
        "locality": "Indiranagar",
        "lat": 12.9734,
        "lon": 77.6432,
        "weight": 10,  # Hotspot: high ghee roast dosa volume
        "tags": ["ghee_dosa", "south_indian", "hotspot"]
    }
]

# Hub locations across Bangalore for initial rider distribution
RIDER_HUBS: List[Tuple[float, float, str]] = [
    (12.9784, 77.6408, "Indiranagar"),
    (12.9352, 77.6245, "Koramangala"),
    (12.9116, 77.6389, "HSR Layout"),
    (12.9166, 77.6101, "BTM"),
    (12.9308, 77.5838, "Jayanagar"),
    (12.9063, 77.5857, "JP Nagar"),
    (12.9757, 77.6068, "MG Road"),
    (13.0035, 77.5710, "Malleshwaram"),
    (12.9569, 77.7011, "Marathahalli"),
    (12.9698, 77.7500, "Whitefield"),
    (13.0358, 77.5970, "Hebbal"),
    (12.8452, 77.6602, "Electronic City"),
    (12.9406, 77.5738, "Basavanagudi"),
    (12.9716, 77.5946, "City Center (Cubbon Park)"),
    (12.9500, 77.6300, "Domlur / EGL Tech Park")
]

