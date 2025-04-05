import requests
import json

# Base URL for NHS FHIR Terminology Server
BASE_URL = "https://ontology.nhs.uk/production1/fhir/"

# Optional: Add an NHS API key if required
API_KEY = None  # Replace with your API key if needed

def get_medicine_by_code(code):
    """
    Fetches details of a medicine using its dm+d code.
    
    :param code: The dm+d code (e.g., '42109611000001109' for Paracetamol 500mg tablets)
    :return: JSON response with medicine details
    """
    url = f"{BASE_URL}CodeSystem/dmd"  # Adjusted endpoint for dm+d lookup
    params = {"code": code}

    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        return response.json()  # Return the JSON response
    except requests.exceptions.HTTPError as http_err:
        return {"error": f"HTTP error occurred: {http_err}"}
    except requests.exceptions.ConnectionError:
        return {"error": "Failed to connect to NHS API. Check your network or API URL."}
    except requests.exceptions.Timeout:
        return {"error": "Request timed out. NHS API may be down or slow."}
    except requests.exceptions.RequestException as err:
        return {"error": f"An error occurred: {err}"}

def pretty_print_json(data):
    """
    Prints JSON data in a readable format.
    """
    print(json.dumps(data, indent=4, sort_keys=True))

if __name__ == "__main__":
    # Example dm+d code for 'Paracetamol 500mg tablets'
    dmd_code = "42109611000001109"
    print(f"\n🔹 Fetching medicine details for dm+d code: {dmd_code}")
    medicine_details = get_medicine_by_code(dmd_code)
    pretty_print_json(medicine_details)
