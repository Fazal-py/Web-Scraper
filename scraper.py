"""
╔══════════════════════════════════════════════════════════════╗
║              QuoteScraper — Portfolio Web Scraper            ║
║         Built with Python · requests · BeautifulSoup         ║
╚══════════════════════════════════════════════════════════════╝

Scrapes quotes, authors, and tags from quotes.toscrape.com
across all paginated pages, then saves the data to both
JSON and CSV formats.

Usage:
    python scraper.py                         # uses default URL
    python scraper.py --url http://books.toscrape.com
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

# Pretend to be a real browser so we're less likely to be blocked
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_URL   = "http://quotes.toscrape.com"
REQUEST_DELAY = 1.0   # seconds to wait between page requests (be polite!)
MAX_RETRIES   = 3     # how many times to retry a failed request
RETRY_DELAY   = 2.0   # seconds to wait before retrying

OUTPUT_JSON = "quotes.json"
OUTPUT_CSV  = "quotes.csv"


# ─────────────────────────────────────────────
#  TERMINAL COLOUR HELPERS (no dependencies)
# ─────────────────────────────────────────────

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def info(msg):    print(f"{CYAN}[INFO]{RESET}  {msg}")
def success(msg): print(f"{GREEN}[OK]{RESET}    {msg}")
def warn(msg):    print(f"{YELLOW}[WARN]{RESET}  {msg}")
def error(msg):   print(f"{RED}[ERROR]{RESET} {msg}")


# ─────────────────────────────────────────────
#  CORE FUNCTIONS
# ─────────────────────────────────────────────

def fetch_page(url: str, retries: int = MAX_RETRIES) -> str | None:
    """
    Download the raw HTML of a page.

    Retries automatically on failure with a short back-off delay.

    Args:
        url     : Full URL of the page to fetch.
        retries : Number of attempts before giving up.

    Returns:
        HTML string on success, or None if every attempt failed.
    """
    for attempt in range(1, retries + 1):
        try:
            # timeout=(connect_seconds, read_seconds) — don't hang forever
            response = requests.get(url, headers=HEADERS, timeout=(5, 10))

            # Raise an exception for 4xx / 5xx HTTP status codes
            response.raise_for_status()

            return response.text  # ← raw HTML as a string

        except requests.exceptions.Timeout:
            warn(f"Request timed out (attempt {attempt}/{retries}): {url}")

        except requests.exceptions.ConnectionError:
            warn(f"Connection error (attempt {attempt}/{retries}): {url}")

        except requests.exceptions.HTTPError as e:
            error(f"HTTP error {e.response.status_code} for: {url}")
            return None  # Don't retry on client/server HTTP errors

        except requests.exceptions.RequestException as e:
            warn(f"Unexpected request error (attempt {attempt}/{retries}): {e}")

        if attempt < retries:
            info(f"Waiting {RETRY_DELAY}s before retry...")
            time.sleep(RETRY_DELAY)

    error(f"All {retries} attempts failed for: {url}")
    return None


def parse_page(html: str) -> BeautifulSoup:
    """
    Convert raw HTML into a BeautifulSoup object we can search through.

    Args:
        html : Raw HTML string (from fetch_page).

    Returns:
        A BeautifulSoup parse tree.
    """
    # "html.parser" is Python's built-in parser — no extra install needed.
    # Alternatively you could use "lxml" (faster) if you have it installed.
    return BeautifulSoup(html, "html.parser")


def extract_data(soup: BeautifulSoup) -> list[dict]:
    """
    Pull out every quote on the page as a structured dictionary.

    Each quote block on quotes.toscrape.com looks like:
        <div class="quote">
            <span class="text">…</span>
            <small class="author">…</small>
            <div class="tags"><a class="tag">…</a> …</div>
        </div>

    Args:
        soup : Parsed BeautifulSoup object for a single page.

    Returns:
        A list of dicts, one per quote, with keys:
        quote, author, tags, scraped_at.
    """
    quotes = []

    # Find every quote container on the page
    quote_blocks = soup.find_all("div", class_="quote")

    for block in quote_blocks:
        # --- Quote text ---
        # The .text CSS class holds the actual quote (with surrounding "…")
        text_tag = block.find("span", class_="text")
        quote_text = text_tag.get_text(strip=True) if text_tag else "N/A"

        # --- Author ---
        author_tag = block.find("small", class_="author")
        author = author_tag.get_text(strip=True) if author_tag else "Unknown"

        # --- Tags ---
        # There can be zero or many tags; collect them all into a list
        tag_elements = block.find_all("a", class_="tag")
        tags = [t.get_text(strip=True) for t in tag_elements]

        quotes.append({
            "quote":      quote_text,
            "author":     author,
            "tags":       tags,              # kept as a list for JSON richness
            "tags_csv":   ", ".join(tags),   # flattened string for CSV column
            "scraped_at": datetime.utcnow().isoformat() + "Z",
        })

    return quotes


def get_next_page_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """
    Find the URL of the next page, or None if we're on the last page.

    The pagination link looks like:
        <li class="next"><a href="/page/2/">Next →</a></li>

    Args:
        soup     : Parsed BeautifulSoup for the current page.
        base_url : Root URL of the site (so we can build an absolute URL).

    Returns:
        Absolute URL string for the next page, or None.
    """
    next_btn = soup.find("li", class_="next")
    if next_btn:
        anchor = next_btn.find("a")
        if anchor and anchor.get("href"):
            # href is a relative path like "/page/2/" — prepend the base URL
            return base_url.rstrip("/") + anchor["href"]
    return None


# ─────────────────────────────────────────────
#  OUTPUT FUNCTIONS
# ─────────────────────────────────────────────

def save_to_json(data: list[dict], filepath: str = OUTPUT_JSON) -> None:
    """
    Write the list of quote dictionaries to a JSON file.

    Args:
        data     : List of quote dicts produced by extract_data().
        filepath : Destination file path.
    """
    with open(filepath, "w", encoding="utf-8") as f:
        # indent=2 makes the file human-readable; ensure_ascii=False keeps
        # special characters (e.g. curly quotes) as-is instead of escaping them
        json.dump(data, f, indent=2, ensure_ascii=False)

    success(f"Saved {len(data)} quotes → {filepath}")


def save_to_csv(data: list[dict], filepath: str = OUTPUT_CSV) -> None:
    """
    Write the list of quote dictionaries to a CSV file.

    Tags are stored as a comma-separated string in the 'tags' column.

    Args:
        data     : List of quote dicts produced by extract_data().
        filepath : Destination file path.
    """
    if not data:
        warn("No data to write — CSV not created.")
        return

    # Use only the columns we want in the CSV (drop 'tags' list, keep 'tags_csv')
    csv_fields = ["quote", "author", "tags_csv", "scraped_at"]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    success(f"Saved {len(data)} quotes → {filepath}")


# ─────────────────────────────────────────────
#  MAIN ORCHESTRATOR
# ─────────────────────────────────────────────

def run_scraper(start_url: str) -> None:
    """
    Crawl every page starting from start_url, extract quotes, and save output.

    Pagination is followed automatically until there are no more pages.

    Args:
        start_url : The first page URL to begin scraping from.
    """
    all_quotes  = []   # accumulate every quote across all pages
    current_url = start_url
    page_num    = 1

    # Derive the base URL so we can build absolute "next page" links
    # e.g. "http://quotes.toscrape.com/page/2" → base = "http://quotes.toscrape.com"
    from urllib.parse import urlparse
    parsed   = urlparse(start_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    print()
    print(f"{BOLD}{'─' * 56}{RESET}")
    print(f"{BOLD}  QuoteScraper  |  {start_url}{RESET}")
    print(f"{BOLD}{'─' * 56}{RESET}")
    print()

    while current_url:
        info(f"Scraping page {page_num}  →  {current_url}")

        # Step 1: Download the page HTML
        html = fetch_page(current_url)
        if html is None:
            error("Could not fetch page — stopping early.")
            break

        # Step 2: Parse HTML into a searchable tree
        soup = parse_page(html)

        # Step 3: Pull out the structured data
        page_quotes = extract_data(soup)

        if page_quotes:
            all_quotes.extend(page_quotes)
            success(f"  Found {len(page_quotes)} quotes on page {page_num}  "
                    f"(total so far: {len(all_quotes)})")
        else:
            warn(f"  No quotes found on page {page_num}.")

        # Step 4: Find the next page link (or stop if there isn't one)
        current_url = get_next_page_url(soup, base_url)
        page_num   += 1

        # Be polite — pause before hitting the next page
        if current_url:
            time.sleep(REQUEST_DELAY)

    # ── Summary ──────────────────────────────
    print()
    print(f"{BOLD}{'─' * 56}{RESET}")
    info(f"Scraping complete. {len(all_quotes)} quotes collected "
         f"across {page_num - 1} page(s).")
    print(f"{BOLD}{'─' * 56}{RESET}")
    print()

    if not all_quotes:
        error("No quotes were collected. Nothing to save.")
        sys.exit(1)

    # Step 5: Save results
    save_to_json(all_quotes, OUTPUT_JSON)
    save_to_csv(all_quotes,  OUTPUT_CSV)

    print()
    success("All done! Check quotes.json and quotes.csv in this directory.")
    print()


# ─────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="QuoteScraper — scrape quotes.toscrape.com to JSON & CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py
  python scraper.py --url http://quotes.toscrape.com
        """,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Starting URL to scrape (default: {DEFAULT_URL})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_scraper(args.url)
