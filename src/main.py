import requests
import re
import json
import os
import argparse
from collections import defaultdict
from datetime import datetime
import configparser

# Load CLIENT_ID and CLIENT_SECRET from external file
with open("credentials.json", "r") as f:
    credentials = json.load(f)

CLIENT_ID = credentials.get("CLIENT_ID")
CLIENT_SECRET = credentials.get("CLIENT_SECRET")

# NHS Terminology Server OAuth2 Token Endpoint
TOKEN_URL = "https://ontology.nhs.uk/authorisation/auth/realms/nhs-digital-terminology/protocol/openid-connect/token"

# NHS Terminology Server API Endpoints
LOOKUP_URL = "https://ontology.nhs.uk/production1/fhir/CodeSystem/$lookup"

# Read the configuration from config.ini
config = configparser.ConfigParser()
config.read('src/config.ini')

# Get the preview_base_url from the DEFAULT section
PREVIEW_BASE_URL = config['DEFAULT'].get('preview_base_url', '').strip()

def get_access_token():
    """
    Retrieves an OAuth2 access token from the NHS Terminology Server.
    """
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    
    response = requests.post(TOKEN_URL, headers=headers, data=data)

    if response.status_code == 200:
        return response.json().get('access_token')
    else:
        raise Exception(f"Failed to obtain token: {response.status_code} - {response.text}")

def get_report_versions():
    """
    Scans the reports directory and returns a list of dm+d version strings
    extracted from filenames like: dmd_lookup_report_202503_4_0.html
    Converts underscores back to dots.
    """
    reports_dir = os.path.join(os.getcwd(), "reports")
    if not os.path.exists(reports_dir):
        return []

    versions = []
    pattern = re.compile(r"dmd_lookup_report_([\d_]+)\.html")

    for filename in os.listdir(reports_dir):
        match = pattern.match(filename)
        if match:
            raw_version = match.group(1)
            version = raw_version.replace("_", ".")
            versions.append(version)

    return sorted(versions)        
        
def get_dmd_version_via_lookup(access_token, code="96062004"):
    """
    Performs a $lookup on a known dm+d code (default: 96062004) to extract the current version.
    """
    url = "https://ontology.nhs.uk/production1/fhir/CodeSystem/$lookup"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    payload = {
        "resourceType": "Parameters",
        "parameter": [
            { "name": "system", "valueUri": "https://dmd.nhs.uk" },
            { "name": "code", "valueCode": code }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(
            f"Failed to perform $lookup:\n"
            f"Status Code: {response.status_code}\n"
            f"Reason: {response.reason}\n"
            f"URL: {response.url}\n"
            f"Response Text: {response.text}"
        )

    # Try to extract version from Parameters
    parameters = response.json().get("parameter", [])
    for param in parameters:
        if param.get("name") == "version":
            return param.get("valueString")

    return None  # No version found

def check_if_up_to_date(access_token):
    latest_published_report = check_latest_published_report()
    try:
        latest_published_report = datetime.strptime(latest_published_report, "%Y-%m")
    except ValueError as e:
        raise ValueError(f"Invalid date format in latest_published_report: {latest_published_report}") from e

    latest_published_data = check_latest_published_data()
    if latest_published_report >= latest_published_data:
        return True
    else:
        return False
           
def extract_dmd_id_from_sql_files():
    base_api_url = "https://api.github.com/repos/bennettoxford/openprescribing-hospitals/contents/viewer/measures"
    raw_base_url = "https://raw.githubusercontent.com/bennettoxford/openprescribing-hospitals/main/viewer/measures"
    html_base_url = "https://github.com/bennettoxford/openprescribing-hospitals/tree/main/viewer/measures"

    code_objects = []

    response = requests.get(base_api_url)
    if response.status_code != 200:
        raise Exception(
            f"Failed to fetch directory:\n"
            f"Status Code: {response.status_code}\n"
            f"Reason: {response.reason}\n"
            f"URL: {response.url}\n"
            f"Response Text: {response.text}"
        )
    
    folders = [item['name'] for item in response.json() if item['type'] == 'dir']

    for folder in folders:
        folder_api_url = f"{base_api_url}/{folder}"
        folder_html_url = f"{html_base_url}/{folder}"
        folder_response = requests.get(folder_api_url)

        if folder_response.status_code != 200:
            continue

        files = folder_response.json()
        sql_file = next((f for f in files if f['name'].endswith('.sql')), None)

        if sql_file:
            raw_url = f"{raw_base_url}/{folder}/{sql_file['name']}"
            sql_response = requests.get(raw_url)

            if sql_response.status_code == 200:
                sql_text = sql_response.text
                long_numbers = re.findall(r'\b\d{7,}\b', sql_text)
                unique_numbers = set(long_numbers)

                for code in unique_numbers:
                    code_objects.append(DmdCode(code=code, folder=folder, url=folder_html_url))

    return code_objects

def build_lookup_bundle(codes, system_url="https://dmd.nhs.uk"):
    """
    Constructs a FHIR batch Bundle to look up multiple codes.
    """
    entries = []
    for code in codes:
        entries.append({
            "request": {
                "method": "POST",
                "url": "CodeSystem/$lookup"
            },
            "resource": {
                "resourceType": "Parameters",
                "parameter": [
                    { "name": "system", "valueUri": system_url },
                    { "name": "code", "valueCode": code }
                ]
            }
        })
    
    return {
        "resourceType": "Bundle",
        "type": "batch",
        "entry": entries
    }


def send_lookup_bundle(access_token, bundle):
    """
    Sends a batch bundle to the NHS Terminology Server for $lookup.
    """
    url = "https://ontology.nhs.uk/production1/fhir"  # Root FHIR endpoint for batches
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/fhir+json',
        'Accept': 'application/fhir+json'
    }

    response = requests.post(url, headers=headers, json=bundle)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Batch lookup failed: {response.status_code} - {response.text}")

        
def parse_lookup_responses(response_bundle):
    """
    Parses a response bundle from the NHS Terminology Server $lookup batch.
    Returns a dict mapping code → status ('active', 'inactive', or 'unknown').
    """
    status_map = {}

    for entry in response_bundle.get("entry", []):
        resource = entry.get("resource", {})
        code = None
        status = "unknown"

        if resource.get("resourceType") == "Parameters":
            parameters = resource.get("parameter", [])

            # Extract code
            for p in parameters:
                if p.get("name") == "code":
                    code = p.get("valueCode")

            # Look for inactive property
            for p in parameters:
                if p.get("name") == "property":
                    part_list = p.get("part", [])
                    is_inactive_property = any(
                        part.get("name") == "code" and part.get("valueCode") == "inactive"
                        for part in part_list
                    )
                    if is_inactive_property:
                        for part in part_list:
                            if part.get("name") == "value":
                                if part.get("valueBoolean") is True:
                                    status = "inactive"
                                elif part.get("valueBoolean") is False:
                                    status = "active"

        elif resource.get("resourceType") == "OperationOutcome":
            diagnostics = resource.get("issue", [{}])[0].get("diagnostics", "")
            match = re.search(r'\b\d{7,}\b', diagnostics)
            if match:
                code = match.group(0)
            status = "unknown"

        if code:
            status_map[code] = status

    return status_map

def write_dmd_lookup_report_html(code_objects, version):
    """
    Generates a styled HTML report for dm+d lookup results grouped by status and folder.
    Filename is based on the CodeSystem version.
    """
    reports_dir = os.path.join(os.getcwd(), "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Read base64 logo
    image_path = os.path.join(os.getcwd(), "src", "base64_image.txt")
    with open(image_path, "r") as file:
        base64_image = file.read()

    # Group by status → folder → list of codes
    grouped = {
        "unknown": defaultdict(list),
        "inactive": defaultdict(list),
        "active": defaultdict(list),
    }

    for obj in code_objects:
        status = (obj.status or "unknown").lower()
        grouped[status][obj.folder].append(obj)

    link = f"https://github.com/chrisjwood16/dmd_tests/blob/main/reports/"

    # Begin HTML
    report = f"""
    <html>
    <head>
    <title>dm+d Lookup Report – version {version}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f8f9fa;
            margin: 20px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background-color: white;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        header img {{
            max-width: 650px;
        }}
        h2 {{
            color: #222;
            margin-top: 40px;
        }}
        h3 {{
            margin-top: 30px;
            color: #444;
        }}
        ul {{
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 4px;
        }}
        .status-box {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 5px;
            font-size: 0.9em;
        }}
        .active {{ background-color: #d7f0d2; color: #0f7b0f; }}
        .inactive {{ background-color: #fbdcdc; color: #b30000; }}
        .unknown {{ background-color: #fff6cc; color: #cc7a00; }}
    </style>
    </head>
    <body>
    <div class="container">
        <header>
            <img src="{base64_image}" alt="OpenPrescribing logo" />
            <h2>dm+d Lookup Report – version {version}</h2>
            <div class="back-link"><p><a href="{PREVIEW_BASE_URL}{link}list_dmd_lookup_reports.html">← Back to all reports</a></p></div>
            <p>This report lists all dm+d codes extracted from SQL files in OpenPrescribing Hospitals and their lookup status via the NHS Terminology Server.</p>
        </header>
    """

    def render_status_section(label, css_class, folder_dict):
        section_html = f"<h2>{label} <span class='status-box {css_class}'>{css_class.capitalize()}</span></h2>\n"
        if not folder_dict:
            return section_html + "<p>No codes found.</p>"
        for folder in sorted(folder_dict.keys()):
            objs = folder_dict[folder]
            section_html += f"<h3>Folder: <a href='{objs[0].url}'>{folder}</a></h3>\n<ul>\n"
            for obj in objs:
                section_html += f"<li>{obj.code}</li>\n"
            section_html += "</ul>\n"
        return section_html

    # Render sections in order
    report += render_status_section("Unknown codes", "unknown", grouped["unknown"])
    report += render_status_section("Inactive codes", "inactive", grouped["inactive"])
    report += render_status_section("Active codes", "active", grouped["active"])

    # Close HTML
    report += """
    </div>
    </body>
    </html>
    """

    # Write file using version in name
    safe_version = version.replace(".", "_")
    filename = f"dmd_lookup_report_{safe_version}.html"
    filepath = os.path.join(reports_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    filename = f"dmd_lookup_report_latest.html"
    filepath = os.path.join(reports_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report written to: {filepath}")

def update_reports(access_token, version):
    code_objects = extract_dmd_id_from_sql_files()
    unique_codes = list({obj.code for obj in code_objects})
    
    bundle = build_lookup_bundle(unique_codes)
    response_bundle = send_lookup_bundle(access_token, bundle)
    status_map = parse_lookup_responses(response_bundle)

    for obj in code_objects:
        obj.set_status(status_map.get(obj.code, "unknown"))
        
    write_dmd_lookup_report_html(code_objects, version)
    generate_dmd_lookup_index_html()

    return code_objects

def generate_dmd_lookup_index_html():
    import os
    import re
    from datetime import datetime

    reports_dir = os.path.join(os.getcwd(), "reports")

    # Read base64 logo
    image_path = os.path.join(os.getcwd(), "src", "base64_image.txt")
    with open(image_path, "r") as f:
        base64_image = f.read()

    # Get all report files
    html_files = [
        f for f in os.listdir(reports_dir)
        if f.startswith("dmd_lookup_report_") and f.endswith(".html")
    ]

    version_files = []
    for filename in html_files:
        match = re.match(r"dmd_lookup_report_([\d_]+)\.html", filename)
        if match:
            version_raw = match.group(1)
            version = version_raw.replace("_", ".")
            try:
                dt = datetime.strptime(version.split('.')[0], "%Y%m")
                version_files.append((dt, version, filename))
            except ValueError:
                continue

    version_files.sort(reverse=True)

    html_content = f"""
    <html>
    <head>
    <title>dm+d Lookup Reports</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f8f9fa;
            margin: 20px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: white;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        header {{
            text-align: center;
            margin-bottom: 40px;
        }}
        header img {{
            max-width: 650px;
            margin-bottom: 10px;
        }}
        h2 {{
            color: #333;
        }}
        ul {{
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 10px;
        }}
        a {{
            text-decoration: none;
            color: #0485d1;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
    </head>
    <body>
    <div class="container">
        <header>
            <img src="{base64_image}" alt="OpenPrescribing logo">
            <h2>dm+d Lookup Reports Index</h2>
        </header>
        <ul>
    """

    for i, (_, version, filename) in enumerate(version_files):
        label = f"{version}"
        if i == 0:
            label += " ← Latest"
        link = f"https://github.com/chrisjwood16/dmd_tests/blob/main/reports/{filename}"
        html_content += f'<li><a href="{PREVIEW_BASE_URL}{link}">{label}</a></li>\n'

    html_content += """
        </ul>
    </div>
    </body>
    </html>
    """

    output_path = os.path.join(reports_dir, "list_dmd_lookup_reports.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Index written to: {output_path}")


class DmdCode:
    def __init__(self, code, folder, url):
        self.code = code
        self.folder = folder
        self.url = url
        self.status = None  # e.g. "active", "inactive", "unknown"

    def set_status(self, status):
        self.status = status

    def __repr__(self):
        return f"DmdCode(code={self.code}, folder='{self.folder}', url='{self.url}', status='{self.status}')"


def main():
    # Create the parser
    parser = argparse.ArgumentParser(description="Process an optional mode argument.")
    
    # Add the optional mode argument
    parser.add_argument(
        "--mode", 
        choices=["auto", "force"], 
        default="auto", 
        help="Specify the mode of operation. Choices are 'auto' (default) or 'force'."
    )
    
    # Parse the command-line arguments
    args = parser.parse_args()
    
    # Access the mode argument
    mode = args.mode

    access_token = get_access_token()
    existing_versions = get_report_versions()
    version = get_dmd_version_via_lookup(access_token)

    if mode == "force":
        update_reports(access_token, version)
    elif mode == "auto":
        if version in existing_versions:
            print(f"Version {version} already exists in reports directory.")
        else:
            update_reports(access_token, version)

def main():
    parser = argparse.ArgumentParser(description="Generate dm+d status report")
    parser.add_argument("--mode", choices=["auto", "force"], default="auto")
    parser.add_argument("--fail-on-problem", action="store_true")
    args = parser.parse_args()

    access_token = get_access_token()
    existing_versions = get_report_versions()
    version = get_dmd_version_via_lookup(access_token)

    should_run = args.mode == "force" or version not in existing_versions

    if should_run:
        code_objects = update_reports(access_token, version)

        # After report is written, fail if needed
        if args.fail_on_problem:
            code_objects[0].set_status('inactive')
            code_objects[1].set_status('unknown')
            problems = [obj for obj in code_objects if obj.status in ("inactive", "unknown")]
            if problems:
                print("\nIssues detected with the following codes:\n")
                for obj in problems:
                    print(f"- {obj.code} ({obj.status}) in folder '{obj.folder}'")
                print("\nFailing workflow due to problem codes.\n")
                exit(1)
    else:
        print(f"Version {version} already processed.")

if __name__ == "__main__":
    main()