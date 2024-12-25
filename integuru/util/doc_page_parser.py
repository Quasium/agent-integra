import requests
import re
import yaml
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Playwright for handling complex JS-driven pages
from playwright.sync_api import sync_playwright

def detect_documentation_type(html_content):
    """
    Detect whether the given HTML content is from:
      - OpenAPI/Swagger
      - Postman
      - Unknown/Other

    Returns: "openapi", "swagger", "postman", or "unknown"
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Look for Swagger / OpenAPI references
    # Check for scripts or links referencing swagger-ui or ReDoc
    swagger_ui = soup.find('script', src=re.compile(r'swagger-ui', re.IGNORECASE))
    redoc = soup.find('script', src=re.compile(r'redoc', re.IGNORECASE))
    if swagger_ui or redoc:
        # Strong indicator of OpenAPI/Swagger-based docs
        return "openapi"

    # Check for a div with swagger UI
    swagger_div = soup.find(id='swagger-ui')
    if swagger_div:
        return "swagger"

    # 2. Look for Postman references
    postman_link = soup.find('a', href=re.compile(r'getpostman|documenter\.getpostman\.com', re.IGNORECASE))
    if postman_link:
        return "postman"

    # Look for a "Run in Postman" button
    run_in_postman = soup.find('img', alt=re.compile(r'Run in Postman', re.IGNORECASE))
    if run_in_postman:
        return "postman"

    # If not found anything relevant
    return "unknown"


def find_spec_link(html_content, base_url):
    """
    Attempt to find a direct link to the underlying API spec file
    (e.g., swagger.json, openapi.yaml, postman_collection.json).
    Returns the absolute URL of the spec or None if not found.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Look for script/link tags referencing swagger.json, openapi.* or postman_collection.json
    script_tags = soup.find_all('script', src=True)
    link_tags = soup.find_all('link', href=True)
    anchor_tags = soup.find_all('a', href=True)

    patterns = [
        r'swagger\.json',
        r'openapi\.json',
        r'openapi\.yaml',
        r'openapi\.yml',
        r'postman_collection\.json'
    ]

    for pattern in patterns:
        # Check script src
        for tag in script_tags:
            src = tag.get('src', '')
            if re.search(pattern, src, re.IGNORECASE):
                return urljoin(base_url, src)
        # Check link href
        for tag in link_tags:
            href = tag.get('href', '')
            if re.search(pattern, href, re.IGNORECASE):
                return urljoin(base_url, href)
        # Check anchor href
        for tag in anchor_tags:
            href = tag.get('href', '')
            if re.search(pattern, href, re.IGNORECASE):
                return urljoin(base_url, href)

    # 2. Search entire HTML for direct references (fallback)
    combined_pattern = r'https?://[^"\'<>\s]+(?:swagger\.json|openapi\.(?:json|yaml|yml)|postman_collection\.json)'
    match = re.search(combined_pattern, html_content, re.IGNORECASE)
    if match:
        return match.group(0)

    return None


def retrieve_api_spec(spec_url):
    """
    Download the spec file from the given URL.
    Returns the raw text of the spec or None if there's an error.
    """
    try:
        resp = requests.get(spec_url, timeout=10)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Failed to retrieve spec from {spec_url}: {e}")
        return None


def parse_api_spec(spec_text):
    """
    Parse the spec text as JSON or YAML and return a Python dictionary.
    """
    # Try JSON
    try:
        return json.loads(spec_text)
    except json.JSONDecodeError:
        pass

    # Try YAML
    try:
        return yaml.safe_load(spec_text)
    except yaml.YAMLError:
        pass

    return None


def reconstruct_definition(spec_dict, doc_type):
    """
    Based on doc_type ("openapi", "swagger", "postman"),
    returns the canonical JSON format of the specification.

    In real usage, you might refine or validate the structure further.
    """
    if not spec_dict:
        return None

    # For demonstration, we simply return the JSON-serialized version
    # of the specification dictionary.
    return json.dumps(spec_dict, indent=2)


def fetch_html_dynamic(url):
    """
    Fetch the fully rendered HTML content of a URL using Playwright
    for pages that require JavaScript to load API spec references.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='networkidle')  # Wait for network requests to finish
            html_content = page.content()
            browser.close()
        return html_content
    except Exception as e:
        print(f"Playwright error when fetching {url}: {e}")
        return None


def fetch_documentation_html(url, use_playwright=False):
    """
    Attempt to fetch HTML from a URL using:
      1. requests (fast, but static)
      2. fallback to Playwright if use_playwright=True or requests fails

    Returns the HTML string or None.
    """
    # First attempt with requests (static approach)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        # Check if there's enough content (very naive check)
        if len(resp.text) > 300:
            return resp.text
    except Exception as e:
        print(f"Requests failed for {url}: {e}")

    if use_playwright:
        # Fallback to dynamic approach
        print("Trying to fetch page with Playwright for dynamic rendering...")
        return fetch_html_dynamic(url)

    return None


def parse_api_documentation(url, use_playwright=False):
    """
    Main function:
      1. Fetch the documentation HTML (either static or dynamic).
      2. Detect the doc type (OpenAPI/Swagger/Postman).
      3. Locate and retrieve the underlying spec (if any).
      4. Convert it back to the original format.

    Returns a tuple of (doc_type, reconstructed_spec).
    """
    html_content = fetch_documentation_html(url, use_playwright=use_playwright)
    if not html_content:
        print("Could not fetch any HTML content.")
        return None, None

    # 1. Detect documentation type
    doc_type = detect_documentation_type(html_content)
    print(f"Detected documentation type: {doc_type}")

    # 2. Find spec link (try to locate swagger.json, openapi.yaml, or postman_collection.json)
    spec_url = find_spec_link(html_content, url)
    if not spec_url:
        print("No direct spec link found in the HTML.")
        # Try a JavaScript approach with Playwright (if not already done)
        if not use_playwright:
            print("Re-attempting with Playwright for potential dynamic content...")
            return parse_api_documentation(url, use_playwright=True)
        else:
            return doc_type, None

    print(f"Found spec link: {spec_url}")

    # 3. Retrieve the spec
    spec_text = retrieve_api_spec(spec_url)
    if not spec_text:
        print("Failed to retrieve the spec file.")
        return doc_type, None

    # 4. Parse the spec into a dictionary
    spec_dict = parse_api_spec(spec_text)
    if not spec_dict:
        print("Could not parse spec as JSON or YAML.")
        return doc_type, None

    # 5. Reconstruct it into a canonical format
    final_definition = reconstruct_definition(spec_dict, doc_type)
    return doc_type, final_definition


if __name__ == "__main__":
    # Example usage:
    # You may replace this with any public documentation link you want to test.
    test_url = "https://petstore.swagger.io/"

    doc_type, spec = parse_api_documentation(test_url, use_playwright=True)

    if doc_type and spec:
        print("\n=== Reconstructed API Definition ===")
        print(spec)
    else:
        print("\nCould not reconstruct the API definition.")
