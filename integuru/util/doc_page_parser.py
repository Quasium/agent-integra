from typing import Optional, Tuple, Dict, Any, Union, List, Set
import requests
import re
import yaml
import json
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass
from bs4 import BeautifulSoup

# Playwright for handling complex JS-driven pages
from playwright.sync_api import sync_playwright
from playwright.sync_api._generated import Page, Browser

@dataclass
class DocTypeResult:
    doc_type: str
    confidence: float

@dataclass 
class DocPage:
    url: str
    title: str
    content: str
    spec: Optional[Dict[str, Any]] = None

def detect_documentation_type(html_content: str) -> DocTypeResult:
    """
    Detect whether the given HTML content is from:
      - OpenAPI/Swagger
      - Postman
      - Unknown/Other

    Returns: DocTypeResult with doc_type and confidence score
    """
    if not html_content:
        return DocTypeResult("unknown", 0.0)

    soup = BeautifulSoup(html_content, 'html.parser')
    confidence = 0.0

    # 1. Look for Swagger / OpenAPI references
    swagger_ui = soup.find('script', src=re.compile(r'swagger-ui', re.IGNORECASE))
    redoc = soup.find('script', src=re.compile(r'redoc', re.IGNORECASE))
    if swagger_ui or redoc:
        confidence = 0.9
        return DocTypeResult("openapi", confidence)

    swagger_div = soup.find(id='swagger-ui')
    if swagger_div:
        confidence = 0.8
        return DocTypeResult("swagger", confidence)

    # 2. Look for Postman references
    postman_link = soup.find('a', href=re.compile(r'getpostman|documenter\.getpostman\.com', re.IGNORECASE))
    if postman_link:
        confidence = 0.7
        return DocTypeResult("postman", confidence)

    run_in_postman = soup.find('img', alt=re.compile(r'Run in Postman', re.IGNORECASE))
    if run_in_postman:
        confidence = 0.6
        return DocTypeResult("postman", confidence)

    return DocTypeResult("unknown", 0.0)

def extract_doc_links(html_content: str, base_url: str) -> Set[str]:
    """
    Extract all documentation page links from HTML content.
    
    Args:
        html_content: Raw HTML content to search
        base_url: Base URL to resolve relative URLs
        
    Returns:
        Set[str]: Set of absolute URLs for documentation pages
    """
    if not html_content or not base_url:
        return set()

    soup = BeautifulSoup(html_content, 'html.parser')
    links = set()
    base_domain = urlparse(base_url).netloc

    # Common documentation navigation elements
    nav_elements = soup.find_all(['nav', 'div'], class_=re.compile(r'nav|menu|sidebar|toc', re.IGNORECASE))
    
    for nav in nav_elements:
        for a in nav.find_all('a', href=True):
            url = urljoin(base_url, a['href'])
            if urlparse(url).netloc == base_domain:
                links.add(url)

    # Also look for links in main content area
    main_content = soup.find(['main', 'article', 'div'], 
                           class_=re.compile(r'content|main|documentation', re.IGNORECASE))
    if main_content:
        for a in main_content.find_all('a', href=True):
            url = urljoin(base_url, a['href'])
            if urlparse(url).netloc == base_domain:
                links.add(url)

    return links

def find_spec_link(html_content: str, base_url: str) -> Optional[str]:
    """
    Attempt to find a direct link to the underlying API spec file.
    
    Args:
        html_content: Raw HTML content to search
        base_url: Base URL to resolve relative URLs
        
    Returns:
        Optional[str]: Absolute URL of the spec if found, None otherwise
    """
    if not html_content or not base_url:
        return None

    soup = BeautifulSoup(html_content, 'html.parser')

    patterns = [
        r'swagger\.json',
        r'openapi\.json',
        r'openapi\.ya?ml',
        r'postman_collection\.json'
    ]

    # Search in script, link and anchor tags
    for tag_type, attr in [('script', 'src'), ('link', 'href'), ('a', 'href')]:
        for tag in soup.find_all(tag_type, {attr: True}):
            url = tag.get(attr, '')
            if any(re.search(pattern, url, re.IGNORECASE) for pattern in patterns):
                try:
                    return urljoin(base_url, url)
                except Exception:
                    continue

    # Fallback: Search entire HTML
    combined_pattern = r'https?://[^"\'<>\s]+(?:swagger\.json|openapi\.(?:json|ya?ml)|postman_collection\.json)'
    match = re.search(combined_pattern, html_content, re.IGNORECASE)
    return match.group(0) if match else None

def retrieve_api_spec(spec_url: str) -> Optional[str]:
    """
    Download the spec file from the given URL.
    
    Args:
        spec_url: URL to fetch the spec from
        
    Returns:
        Optional[str]: Raw text of the spec if successful, None otherwise
    """
    if not spec_url:
        return None
        
    try:
        resp = requests.get(spec_url, timeout=10)
        resp.raise_for_status()
        return resp.text
    except (requests.RequestException, Exception) as e:
        print(f"Failed to retrieve spec from {spec_url}: {e}")
        return None

def parse_api_spec(spec_text: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Parse the spec text as JSON or YAML.
    
    Args:
        spec_text: Raw text to parse
        
    Returns:
        Optional[Dict]: Parsed spec as dictionary if successful, None otherwise
    """
    if not spec_text:
        return None

    # Try JSON first
    try:
        return json.loads(spec_text)
    except json.JSONDecodeError:
        pass

    # Try YAML as fallback
    try:
        return yaml.safe_load(spec_text)
    except yaml.YAMLError:
        pass

    return None

def reconstruct_definition(spec_dict: Optional[Dict[str, Any]], doc_type: str) -> Optional[str]:
    """
    Convert spec dictionary to canonical JSON format.
    
    Args:
        spec_dict: Parsed spec dictionary
        doc_type: Type of documentation ("openapi", "swagger", "postman")
        
    Returns:
        Optional[str]: JSON string if successful, None otherwise
    """
    if not spec_dict:
        return None

    try:
        return json.dumps(spec_dict, indent=2)
    except (TypeError, ValueError) as e:
        print(f"Failed to serialize spec: {e}")
        return None

def fetch_html_dynamic(url: str) -> Optional[str]:
    """
    Fetch rendered HTML using Playwright.
    
    Args:
        url: URL to fetch
        
    Returns:
        Optional[str]: Rendered HTML if successful, None otherwise
    """
    browser: Optional[Browser] = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page: Page = browser.new_page()
            page.goto(url, wait_until='networkidle', timeout=30000)
            return page.content()
    except Exception as e:
        print(f"Playwright error when fetching {url}: {e}")
        return None
    finally:
        if browser:
            browser.close()

def fetch_documentation_html(url: str, use_playwright: bool = False) -> Optional[str]:
    """
    Fetch HTML using requests or Playwright.
    
    Args:
        url: URL to fetch
        use_playwright: Whether to try Playwright if requests fails
        
    Returns:
        Optional[str]: HTML content if successful, None otherwise
    """
    if not url:
        return None

    # Try requests first
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        if len(resp.text) > 300:
            return resp.text
    except requests.RequestException as e:
        print(f"Requests failed for {url}: {e}")

    if use_playwright:
        print("Trying Playwright for dynamic rendering...")
        return fetch_html_dynamic(url)

    return None

def parse_doc_page(url: str, html_content: str) -> DocPage:
    """
    Parse a single documentation page.
    
    Args:
        url: Page URL
        html_content: HTML content
        
    Returns:
        DocPage: Parsed page information
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Try to find title
    title = ""
    title_elem = soup.find(['h1', 'title'])
    if title_elem:
        title = title_elem.get_text(strip=True)
    
    # Try to find main content
    content = ""
    main_content = soup.find(['main', 'article', 'div'], 
                           class_=re.compile(r'content|main|documentation', re.IGNORECASE))
    if main_content:
        content = main_content.get_text(strip=True)
    
    # Look for API spec
    spec_url = find_spec_link(html_content, url)
    spec = None
    if spec_url:
        spec_text = retrieve_api_spec(spec_url)
        if spec_text:
            spec = parse_api_spec(spec_text)
            
    return DocPage(url=url, title=title, content=content, spec=spec)

def parse_api_documentation(url: str, use_playwright: bool = False) -> List[DocPage]:
    """
    Main function to parse API documentation by crawling all pages.
    
    Args:
        url: Documentation homepage URL
        use_playwright: Whether to try Playwright for dynamic content
        
    Returns:
        List[DocPage]: List of parsed documentation pages
    """
    if not url:
        return []

    visited_urls = set()
    pages_to_visit = {url}
    parsed_pages = []

    while pages_to_visit:
        current_url = pages_to_visit.pop()
        if current_url in visited_urls:
            continue
            
        visited_urls.add(current_url)
        print(f"Processing page: {current_url}")

        html_content = fetch_documentation_html(current_url, use_playwright)
        if not html_content:
            print(f"Could not fetch HTML content for {current_url}")
            continue

        # Parse current page
        doc_page = parse_doc_page(current_url, html_content)
        parsed_pages.append(doc_page)

        # Extract links to other documentation pages
        new_links = extract_doc_links(html_content, current_url)
        print(f"Found {len(new_links)} new links")
        pages_to_visit.update(new_links - visited_urls)

    return parsed_pages

if __name__ == "__main__":
    test_url = "https://api-docs.quiqup.com/docs/api-documentation/4b402d5ab3edd-welcome-to-the-quiqup-api-docs"
    doc_pages = parse_api_documentation(test_url, use_playwright=True)

    print(f"\nFound {len(doc_pages)} documentation pages:")
    for page in doc_pages:
        print(f"\nPage: {page.url}")
        print(f"Title: {page.title}")
        if page.spec:
            print("Found API specification\n\n")
            print(page.spec)
