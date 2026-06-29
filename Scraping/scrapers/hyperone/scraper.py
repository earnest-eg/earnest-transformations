"""
HyperOne Scraper
================
Scrapes product and category data from https://www.hyperone.com.eg/en
Supports static (httpx + BeautifulSoup) and dynamic (Playwright) fallback.
"""

import csv
import json
import logging
import os
import random
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://www.hyperone.com.eg/en"
OUTPUT_DIR = "Hyperone_Data"
REQUEST_DELAY = (1.0, 2.5)
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0
TIMEOUT = 45

GRAPHQL_URL = "https://mcprod.hyperone.com.eg/graphql"
GRAPHQL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0",
    "Origin": "https://www.hyperone.com.eg",
    "Referer": "https://www.hyperone.com.eg/en/",
    "Content-Type": "application/json",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

OUTPUT_DIR_PATH = Path(OUTPUT_DIR)
OUTPUT_DIR_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("HyperOneScraper")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _polite_delay():
    time.sleep(random.uniform(*REQUEST_DELAY))


def _make_client() -> httpx.Client:
    return httpx.Client(
        headers=HEADERS,
        follow_redirects=True,
        timeout=TIMEOUT,
    )


# ---------------------------------------------------------------------------
# GraphQL helpers
# ---------------------------------------------------------------------------

def _call_graphql(query: str, variables: Optional[dict] = None) -> dict:
    """Execute a GraphQL query and return the response data dict."""
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = httpx.post(GRAPHQL_URL, json=payload, headers=GRAPHQL_HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


GRAPHQL_CATEGORY_ID_CACHE: dict[str, str] = {}


def _get_magento_category_id(url_key: str) -> Optional[str]:
    """Resolve a URL key (slug) to a Magento category ID via GraphQL."""
    if url_key in GRAPHQL_CATEGORY_ID_CACHE:
        return GRAPHQL_CATEGORY_ID_CACHE[url_key]
    q = """query { categoryList(filters: { url_key: { eq: "%s" } }) { id } }""" % url_key
    try:
        data = _call_graphql(q)
        items = data.get("data", {}).get("categoryList", [])
        if items:
            cid = str(items[0]["id"])
            GRAPHQL_CATEGORY_ID_CACHE[url_key] = cid
            return cid
    except Exception:
        pass
    return None


PRODUCTS_QUERY = """query Products($catId: String!, $page: Int, $pageSize: Int) {
  products(pageSize: $pageSize, currentPage: $page, filter: { category_id: { eq: $catId } }) {
    items {
      id name sku url_key
      small_image { url }
      price_range {
        minimum_price {
          regular_price { value currency }
          final_price { value }
          discount { percent_off }
        }
      }
      stock_status
      description { html }
      manufacturer
    }
    total_count
  }
}"""


def _fetch_products_via_graphql(url_key: str) -> list[dict[str, Any]]:
    """Fetch products for a category via GraphQL using the URL key."""
    cat_id = _get_magento_category_id(url_key)
    if not cat_id:
        return []
    variables = {"catId": cat_id, "page": 1, "pageSize": 200}
    try:
        data = _call_graphql(PRODUCTS_QUERY, variables)
        return data.get("data", {}).get("products", {}).get("items", [])
    except Exception as exc:
        logger.warning("GraphQL products query failed for %s: %s", url_key, exc)
        return []


# ---------------------------------------------------------------------------
# 1. fetch_url
# ---------------------------------------------------------------------------

def fetch_url(
    url: str,
    session: Optional[httpx.Client] = None,
    use_playwright: bool = False,
) -> tuple[int, str]:
    """Fetch a URL and return (status_code, html).

    When *use_playwright* is True and playwright is available it will be
    used instead of httpx.
    """
    close_session = session is None
    if session is None:
        session = _make_client()

    last_exc: Optional[Exception] = None

    if use_playwright and PLAYWRIGHT_AVAILABLE:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(
                        user_agent=HEADERS["User-Agent"],
                        viewport={"width": 1920, "height": 1080},
                    )
                    page.goto(url, wait_until="networkidle", timeout=TIMEOUT * 1000)
                    html = page.content()
                    browser.close()
                return 200, html
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Playwright attempt %d/%d failed for %s: %s",
                    attempt, MAX_RETRIES, url, exc,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_FACTOR ** attempt)
        raise RuntimeError(
            f"Playwright failed after {MAX_RETRIES} attempts: {last_exc}"
        ) from last_exc

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url)
            if response.status_code == 403 and not use_playwright and PLAYWRIGHT_AVAILABLE:
                logger.info("Got 403 on %s, falling back to Playwright", url)
                return fetch_url(url, session, use_playwright=True)
            if close_session:
                session.close()
            return response.status_code, response.text
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "httpx attempt %d/%d failed for %s: %s",
                attempt, MAX_RETRIES, url, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_FACTOR ** attempt)

    if close_session and session:
        session.close()
    raise RuntimeError(
        f"httpx failed after {MAX_RETRIES} attempts: {last_exc}"
    )


# ---------------------------------------------------------------------------
# 2. parse_embedded_json  (Nuxt __NUXT_DATA__ / JSON-LD)
# ---------------------------------------------------------------------------

def parse_embedded_json(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract structured data from the page.

    Returns a dict with keys:
      - ``nuxt_data`` – the parsed ``__NUXT_DATA__`` array (or None)
      - ``jsonld``    – list of JSON-LD objects found on the page
    """
    result: dict[str, Any] = {"nuxt_data": None, "jsonld": []}

    nuxt_script = soup.find("script", id="__NUXT_DATA__")
    if nuxt_script and nuxt_script.string:
        try:
            result["nuxt_data"] = json.loads(nuxt_script.string)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse __NUXT_DATA__: %s", exc)

    for script in soup.find_all("script", type="application/ld+json"):
        if script.string:
            try:
                data = json.loads(script.string)
                result["jsonld"].append(data)
            except json.JSONDecodeError:
                pass

    return result


def _resolve_ref(val: Any, data: list) -> Any:
    """Resolve a Nuxt data-array reference (integer index) to its value."""
    if isinstance(val, int) and 0 <= val < len(data):
        return data[val]
    return val


# ---------------------------------------------------------------------------
# 3. parse_homepage_categories
# ---------------------------------------------------------------------------

def parse_homepage_categories(html: str, url: str) -> list[dict[str, Any]]:
    """Parse category tree from the homepage HTML.

    Returns a list of category dicts with keys matching ``categories.csv``.
    """
    soup = BeautifulSoup(html, "html.parser")
    embedded = parse_embedded_json(soup)
    categories: list[dict[str, Any]] = []
    seen: set[str] = set()
    scraped_at = _now()

    # -- Method A: extract from __NUXT_DATA__ mega-menu ----------------
    nuxt = embedded.get("nuxt_data")
    if nuxt and isinstance(nuxt, list) and len(nuxt) > 3:
        try:
            idx3 = nuxt[3]
            if isinstance(idx3, dict):
                mm_key = [k for k in idx3 if "category-mega-menu" in k]
                if mm_key:
                    mm = _resolve_ref(idx3[mm_key[0]], nuxt)

                    def _process_node(ref, parent_id=""):
                        node = _resolve_ref(ref, nuxt)
                        if isinstance(ref, list) and ref:
                            node = _resolve_ref(ref[0], nuxt)
                        if not isinstance(node, dict):
                            return
                        nid = str(node.get("id", ""))
                        if not nid or nid in seen:
                            return
                        seen.add(nid)
                        name = str(_resolve_ref(node.get("name", ""), nuxt) or "")
                        url_key = str(_resolve_ref(node.get("url_key", "") or node.get("url", ""), nuxt) or "")
                        level = str(node.get("level", ""))
                        categories.append({
                            "category_id": nid,
                            "category_name": name,
                            "parent_category": parent_id,
                            "category_url": f"{BASE_URL}/category/{url_key}" if url_key else "",
                            "level": level,
                            "scraped_at": scraped_at,
                        })
                        children_ref = node.get("children", [])
                        children = _resolve_ref(children_ref, nuxt)
                        if isinstance(children, list):
                            for child_ref in children:
                                _process_node(child_ref, parent_id=nid)

                    if isinstance(mm, list):
                        for cat_ref in mm:
                            _process_node(cat_ref)
            logger.info(
                "Extracted %d categories from __NUXT_DATA__ mega-menu",
                len(categories),
            )
        except Exception as exc:
            logger.warning("Failed to parse __NUXT_DATA__ categories: %s", exc)

    # -- Method B: fallback — parse <a> links from homepage ------------
    if not categories:
        logger.info("Falling back to HTML link parsing for categories")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/en/category/" not in href:
                continue
            cat_name = a_tag.get_text(strip=True)
            if not cat_name:
                continue
            normalized_href = href if href.startswith("http") else f"{BASE_URL}{href}"
            cat_id = href.rstrip("/").rsplit("/", 1)[-1]
            if cat_id not in seen:
                seen.add(cat_id)
                categories.append({
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "parent_category": "",
                    "category_url": normalized_href,
                    "level": "1",
                    "scraped_at": scraped_at,
                })

    return categories


# ---------------------------------------------------------------------------
# 4. get_all_categories  (recursively discover full tree)
# ---------------------------------------------------------------------------

def get_all_categories(
    session: Optional[httpx.Client] = None,
) -> list[dict[str, Any]]:
    """Discover the full category tree starting from the homepage.

    Returns a flat list of category dicts.
    The __NUXT_DATA__ embedded in the homepage already contains
    the complete tree (including level-38 subcategories), so no
    additional page visits are needed.
    """
    close_session = session is None
    if session is None:
        session = _make_client()

    status, html = fetch_url(BASE_URL, session)
    if status != 200:
        logger.error("Failed to fetch homepage (status %s)", status)
        return []

    categories = parse_homepage_categories(html, BASE_URL)

    if close_session:
        session.close()
    return categories


# ---------------------------------------------------------------------------
# 5. parse_category_products
# ---------------------------------------------------------------------------

def parse_category_products(
    html: str,
    category_name: str = "",
    parent_category: str = "",
    category_url: str = "",
) -> list[dict[str, Any]]:
    """Parse product listings from a category page HTML.

    Tries in order:
      A. GraphQL API (mcprod GraphQL endpoint)
      B. Nuxt __NUXT_DATA__ embedded JSON
      C. HTML product card selectors

    Returns a list of product dicts with keys matching ``products.csv``.
    """
    scraped_at = _now()
    products: list[dict[str, Any]] = []
    seen: set[str] = set()

    # -- Method A: GraphQL API -----------------------------------------
    url_key = ""
    if category_url:
        url_key = category_url.rstrip("/").rsplit("/", 1)[-1]
    if url_key:
        try:
            gql_items = _fetch_products_via_graphql(url_key)
            if gql_items:
                for item in gql_items:
                    pid = str(item.get("id", ""))
                    if pid in seen:
                        continue
                    seen.add(pid)
                    products.append(_graphql_item_to_product(item, category_name, parent_category, scraped_at))
                logger.info("Extracted %d products via GraphQL for '%s'", len(products), url_key)
        except Exception as exc:
            logger.warning("GraphQL extraction failed for %s: %s", url_key, exc)

    # -- Method B: Nuxt __NUXT_DATA__ ----------------------------------
    if not products:
        soup = BeautifulSoup(html, "html.parser")
        embedded = parse_embedded_json(soup)
        nuxt = embedded.get("nuxt_data")
        if nuxt and isinstance(nuxt, list):
            try:
                for item in nuxt:
                    if not isinstance(item, dict):
                        continue
                    for key in item:
                        if "product" not in key.lower():
                            continue
                        raw = _resolve_ref(item[key], nuxt)
                        if not isinstance(raw, list):
                            continue
                        for ref in raw:
                            p = _resolve_ref(ref, nuxt)
                            if isinstance(ref, list):
                                p = _resolve_ref(ref[0], nuxt)
                            if not isinstance(p, dict):
                                continue
                            prod = _extract_product_dict(p, nuxt, category_name, parent_category, scraped_at)
                            if prod and prod["product_id"] not in seen:
                                seen.add(prod["product_id"])
                                products.append(prod)
            except Exception as exc:
                logger.warning("Failed __NUXT_DATA__ product extraction: %s", exc)

    # -- Method C: HTML product card parsing ---------------------------
    if not products:
        soup = BeautifulSoup(html, "html.parser")
        logger.info("Falling back to HTML product card parsing for '%s'", category_name)
        product_elements = soup.find_all(
            ["div", "li", "article"],
            class_=lambda c: c and any(
                kw in str(c).lower() for kw in ["product", "item", "card"]
            ),
        )
        for el in product_elements:
            link = el.find("a", href=True)
            product_url = link["href"] if link else ""
            if product_url and not product_url.startswith("http"):
                product_url = f"{BASE_URL}{product_url}"

            name_el = el.find(
                ["h2", "h3", "h4", "span", "div"],
                class_=lambda c: c and "name" in str(c).lower(),
            ) or el.find(["h2", "h3", "h4"])
            product_name = name_el.get_text(strip=True) if name_el else ""

            pid = product_url.rstrip("/").rsplit("/", 1)[-1] if product_url else str(len(products))
            if pid in seen:
                continue
            seen.add(pid)

            price_el = el.find(
                ["span", "div"],
                class_=lambda c: c and any(
                    kw in str(c).lower() for kw in ["price", "current", "special"]
                ),
            )
            old_price_el = el.find(
                ["span", "div"],
                class_=lambda c: c and "old" in str(c).lower(),
            )

            img = el.find("img", src=True)
            image_url = img["src"] if img else ""

            products.append({
                "product_id": pid,
                "product_name": product_name,
                "brand": "",
                "category_name": category_name,
                "parent_category": parent_category,
                "price": price_el.get_text(strip=True) if price_el else "",
                "old_price": old_price_el.get_text(strip=True) if old_price_el else "",
                "discount": "",
                "currency": "EGP",
                "availability": "",
                "product_url": product_url,
                "image_url": image_url,
                "description": "",
                "sku": "",
                "scraped_at": scraped_at,
            })

    return products


def _graphql_item_to_product(
    item: dict,
    category_name: str,
    parent_category: str,
    scraped_at: str,
) -> dict[str, Any]:
    """Convert a Magento GraphQL product item to the standard product dict."""
    price_range = item.get("price_range", {}).get("minimum_price", {})
    reg_price = price_range.get("regular_price", {})
    final_price = price_range.get("final_price", {})
    discount_info = price_range.get("discount", {})
    img = item.get("small_image", {}) or {}

    price_str = str(final_price.get("value", "") or reg_price.get("value", "") or "")
    old_price_str = ""
    disc_pct = discount_info.get("percent_off", 0)
    if disc_pct:
        old_price_str = str(reg_price.get("value", ""))

    desc = ""
    desc_data = item.get("description", {})
    if isinstance(desc_data, dict):
        desc = desc_data.get("html", "") or desc_data.get("text", "")

    url_key = item.get("url_key", "")
    product_url = f"{BASE_URL}/product/{url_key}" if url_key else ""

    return {
        "product_id": str(item.get("id", "")),
        "product_name": item.get("name", ""),
        "brand": item.get("manufacturer", "") or "",
        "category_name": category_name,
        "parent_category": parent_category,
        "price": price_str,
        "old_price": old_price_str,
        "discount": f"{disc_pct}%" if disc_pct else "",
        "currency": reg_price.get("currency", "EGP"),
        "availability": item.get("stock_status", ""),
        "product_url": product_url,
        "image_url": img.get("url", ""),
        "description": desc,
        "sku": item.get("sku", ""),
        "scraped_at": scraped_at,
    }


def _extract_product_dict(
    p: dict,
    nuxt: list,
    category_name: str,
    parent_category: str,
    scraped_at: str,
) -> Optional[dict[str, Any]]:
    """Extract a single product dict from a Nuxt data object."""
    name = _resolve_ref(p.get("name", ""), nuxt)
    pid = str(_resolve_ref(p.get("id", ""), nuxt))
    sku = str(_resolve_ref(p.get("sku", ""), nuxt))
    if not pid and not sku:
        return None
    product_id = pid or sku

    price = str(_resolve_ref(p.get("price", ""), nuxt) or "")
    old_price = str(
        _resolve_ref(p.get("old_price", "") or p.get("original_price", ""), nuxt) or ""
    )

    discount = ""
    if old_price and price:
        try:
            old_f = float(old_price.replace(",", "").replace("EGP", "").strip())
            new_f = float(price.replace(",", "").replace("EGP", "").strip())
            if old_f > 0:
                discount = f"{int((1 - new_f / old_f) * 100)}%"
        except (ValueError, TypeError):
            pass

    url_key = _resolve_ref(p.get("url_key", "") or p.get("url", ""), nuxt)
    product_url = f"{BASE_URL}/product/{url_key}" if url_key else ""
    image = str(_resolve_ref(p.get("image", "") or p.get("thumbnail", ""), nuxt) or "")
    description = str(_resolve_ref(p.get("description", ""), nuxt) or "")
    brand = str(_resolve_ref(p.get("brand", "") or p.get("manufacturer", ""), nuxt) or "")
    availability = str(_resolve_ref(p.get("availability", "") or p.get("stock_status", ""), nuxt) or "")

    # Remove HTML tags from description
    if description:
        desc_soup = BeautifulSoup(description, "html.parser")
        description = desc_soup.get_text(separator=" ", strip=True)

    return {
        "product_id": product_id,
        "product_name": str(name or ""),
        "brand": brand,
        "category_name": category_name,
        "parent_category": parent_category,
        "price": price,
        "old_price": old_price,
        "discount": discount,
        "currency": "EGP",
        "availability": availability,
        "product_url": product_url,
        "image_url": image,
        "description": description,
        "sku": sku,
        "scraped_at": scraped_at,
    }


# ---------------------------------------------------------------------------
# 6. parse_product_details
# ---------------------------------------------------------------------------

def parse_product_details(
    html: str,
    existing: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Parse a single product detail page.

    *existing* may contain partial data from a listing page; this function
    will fill in the gaps.
    """
    soup = BeautifulSoup(html, "html.parser")
    embedded = parse_embedded_json(soup)
    scraped_at = _now()
    product: dict[str, Any] = existing or {}

    # -- Extract from __NUXT_DATA__ ------------------------------------
    nuxt = embedded.get("nuxt_data")
    if nuxt and isinstance(nuxt, list):
        for item in nuxt:
            if not isinstance(item, dict):
                continue
            d = _extract_product_dict(item, nuxt, "", "", scraped_at)
            if d:
                product.update({k: v for k, v in d.items() if v})
                break

    # -- Extract from JSON-LD (Product schema) -------------------------
    for ld in embedded.get("jsonld", []):
        if isinstance(ld, dict) and ld.get("@type") == "Product":
            product["product_name"] = product.get("product_name") or ld.get("name", "")
            product["description"] = product.get("description") or ld.get("description", "")
            product["sku"] = product.get("sku") or ld.get("sku", "")
            product["product_id"] = product.get("product_id") or ld.get("productID", "") or ld.get("sku", "")
            off = ld.get("offers", {})
            if isinstance(off, dict):
                product["price"] = product.get("price") or str(off.get("price", ""))
                product["currency"] = product.get("currency") or off.get("priceCurrency", "EGP")
                product["availability"] = product.get("availability") or off.get("availability", "")

    # -- Fallback HTML parsing -----------------------------------------
    if not product.get("product_name"):
        title_tag = soup.find("h1") or soup.find("title")
        if title_tag:
            product["product_name"] = title_tag.get_text(strip=True)

    if not product.get("product_url"):
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            product["product_url"] = canonical["href"]

    if not product.get("description"):
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            product["description"] = meta_desc["content"]

    if not product.get("image_url"):
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            product["image_url"] = og_image["content"]

    product.setdefault("scraped_at", scraped_at)
    return product


# ---------------------------------------------------------------------------
# 7-9. Save helpers
# ---------------------------------------------------------------------------

CATEGORY_FIELDS = [
    "category_id", "category_name", "parent_category",
    "category_url", "level", "scraped_at",
]
PRODUCT_FIELDS = [
    "product_id", "product_name", "brand", "category_name",
    "parent_category", "price", "old_price", "discount", "currency",
    "availability", "product_url", "category_url", "image_url", "description", "sku",
    "scraped_at",
]
FAILED_FIELDS = ["url", "category", "error", "timestamp"]


def _write_csv_safe(path: Path, fieldnames: list[str], rows: list[dict[str, Any]], label: str, max_retries: int = 5):
    """Write CSV using a temp file + rename to avoid cross-process locking."""
    tmp_path = path.with_suffix(".csv.tmp")
    for attempt in range(1, max_retries + 1):
        try:
            with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            if path.exists():
                path.unlink()
            tmp_path.rename(path)
            logger.info("Saved %d %s to %s", len(rows), label, path)
            return
        except (PermissionError, OSError):
            if attempt < max_retries:
                logger.warning("File %s locked, retrying in 1s (attempt %d/%d)", path.name, attempt, max_retries)
                time.sleep(1)
            else:
                raise


def save_categories_csv(categories: list[dict[str, Any]]) -> str:
    path = OUTPUT_DIR_PATH / "categories.csv"
    _write_csv_safe(path, CATEGORY_FIELDS, categories, "categories")
    return str(path)


def save_products_csv(products: list[dict[str, Any]]) -> str:
    path = OUTPUT_DIR_PATH / "products.csv"
    _write_csv_safe(path, PRODUCT_FIELDS, products, "products")
    return str(path)


def save_failed_urls(failed: list[dict[str, Any]]) -> str:
    path = OUTPUT_DIR_PATH / "failed_urls.csv"
    _write_csv_safe(path, FAILED_FIELDS, failed, "failed URLs")
    return str(path)


def create_zip() -> str:
    zip_path = OUTPUT_DIR_PATH / "Hyperone_Data.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_name in ["categories.csv", "products.csv", "failed_urls.csv"]:
            file_path = OUTPUT_DIR_PATH / file_name
            if file_path.exists():
                zf.write(file_path, arcname=file_name)
    logger.info("Created archive: %s", zip_path)
    return str(zip_path)


# ---------------------------------------------------------------------------
# 11. main
# ---------------------------------------------------------------------------

def _load_csv(path: Path, fields: list[str]) -> list[dict[str, Any]]:
    """Load rows from an existing CSV file, or return empty list."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception as exc:
        logger.warning("Could not load %s: %s", path.name, exc)
        return []


STATE_FILE = OUTPUT_DIR_PATH / "state.json"


def _save_state(completed_urls: set[str]) -> None:
    """Persist completed category URLs to a JSON file."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"completed_urls": sorted(completed_urls)}, f)
    except Exception as exc:
        logger.warning("Failed to save state: %s", exc)


def _load_state() -> set[str]:
    """Load completed category URLs from JSON file."""
    if not STATE_FILE.exists():
        return set()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("completed_urls", []))
    except Exception as exc:
        logger.warning("Could not load state: %s", exc)
        return set()


def main():
    """Orchestrate the full scrape pipeline. Resumes from existing CSV files."""
    logger.info("=" * 50)
    logger.info("Starting HyperOne Scraper")
    logger.info("=" * 50)

    # Load existing data for resume support
    all_categories: list[dict[str, Any]] = _load_csv(OUTPUT_DIR_PATH / "categories.csv", CATEGORY_FIELDS)
    all_products: list[dict[str, Any]] = _load_csv(OUTPUT_DIR_PATH / "products.csv", PRODUCT_FIELDS)
    failed: list[dict[str, Any]] = _load_csv(OUTPUT_DIR_PATH / "failed_urls.csv", FAILED_FIELDS)
    already_processed: set[str] = _load_state()
    # Also consider failed URLs as processed (won't retry)
    for f in failed:
        if f.get("url"):
            already_processed.add(f["url"])
    logger.info("Loaded %d existing products, %d failed URLs, %d completed categories",
                len(all_products), len(failed), len(already_processed))

    session = _make_client()

    # ---- Step 1: Discover categories (if not already loaded) ----
    if not all_categories:
        try:
            all_categories = get_all_categories(session)
            logger.info("Total categories discovered: %d", len(all_categories))
            save_categories_csv(all_categories)
        except Exception as exc:
            logger.critical("Category discovery failed: %s", exc)
            failed.append({
                "url": BASE_URL,
                "category": "homepage",
                "error": str(exc),
                "timestamp": _now(),
            })
    else:
        logger.info("Reusing %d categories from existing CSV", len(all_categories))

    # ---- Step 2: Scrape products per category ----
    total_succeeded = len(all_products)
    total_failed = len(failed)
    skipped = 0

    for cat in all_categories:
        cat_url = cat["category_url"]
        if not cat_url:
            continue

        if cat_url in already_processed:
            skipped += 1
            continue

        logger.info("Scraping: %s [%s]", cat["category_name"], cat_url)
        _polite_delay()

        try:
            status, html = fetch_url(cat_url, session)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", cat_url, exc)
            failed.append({
                "url": cat_url,
                "category": cat.get("category_name", ""),
                "error": str(exc),
                "timestamp": _now(),
            })
            total_failed += 1
            save_failed_urls(failed)
            already_processed.add(cat_url)
            _save_state(already_processed)
            continue

        if status != 200:
            logger.warning("Bad status %s for %s", status, cat_url)
            failed.append({
                "url": cat_url,
                "category": cat.get("category_name", ""),
                "error": f"HTTP {status}",
                "timestamp": _now(),
            })
            total_failed += 1
            save_failed_urls(failed)
            already_processed.add(cat_url)
            _save_state(already_processed)
            continue

        products = parse_category_products(
            html,
            category_name=cat.get("category_name", ""),
            parent_category=cat.get("parent_category", ""),
            category_url=cat_url,
        )
        all_products.extend(products)
        total_succeeded += 1
        already_processed.add(cat_url)
        logger.info("  -> %d products found (total rows: %d, succeeded: %d, failed: %d, skipped: %d)",
                     len(products), len(all_products), total_succeeded, total_failed, skipped)

        # Save progress after every category
        save_products_csv(all_products)
        save_failed_urls(failed)
        _save_state(already_processed)

    # ---- Step 3: Deduplicate products ----
    raw_count = len(all_products)
    seen_keys: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for p in all_products:
        key = (p.get("product_url", ""), p.get("product_id", ""), p.get("sku", ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(p)

    # ---- Step 4: Save final results ----
    save_categories_csv(all_categories)
    save_products_csv(deduped)
    save_failed_urls(failed)
    archive = create_zip()

    if session:
        session.close()

    logger.info("=" * 50)
    logger.info("SCRAPE COMPLETE")
    logger.info("  Total categories              : %d", len(all_categories))
    logger.info("  Skipped (already done)        : %d", skipped)
    logger.info("  Total succeeded               : %d", total_succeeded)
    logger.info("  Total failed                  : %d", total_failed)
    logger.info("  Raw product rows              : %d", raw_count)
    logger.info("  Final deduplicated products   : %d", len(deduped))
    logger.info("  Categories CSV                : %s", OUTPUT_DIR_PATH / "categories.csv")
    logger.info("  Products CSV                  : %s", OUTPUT_DIR_PATH / "products.csv")
    logger.info("  Failed URLs CSV               : %s", OUTPUT_DIR_PATH / "failed_urls.csv")
    logger.info("  Archive                       : %s", archive)
    logger.info("=" * 50)
    return archive


# ---------------------------------------------------------------------------
# Safe test section  (run only when executed directly with --test)
# ---------------------------------------------------------------------------

def test_scraper():
    """Fetch the homepage and print a brief diagnostic summary."""
    print()
    print("=" * 60)
    print("  HyperOne Scraper — Safe Test")
    print("=" * 60)

    status, html = fetch_url(BASE_URL)
    soup = BeautifulSoup(html, "html.parser")

    page_title = soup.title.string.strip() if soup.title else "(no title)"
    print(f"  Homepage status : {status}")
    print(f"  Page title       : {page_title}")
    print(f"  HTML size        : {len(html):,} bytes")

    categories = parse_homepage_categories(html, BASE_URL)
    print(f"  Categories found : {len(categories)}")

    embedded = parse_embedded_json(soup)
    has_nuxt = embedded["nuxt_data"] is not None
    jsonld_count = len(embedded["jsonld"])
    print(f"  Has __NUXT_DATA__: {has_nuxt}")
    print(f"  JSON-LD blocks   : {jsonld_count}")

    if categories:
        print()
        print("  First 5 categories:")
        for cat in categories[:5]:
            print(f"    [{cat['level']}] {cat['category_name']} -> {cat['category_url']}")

    print()
    print("  Test complete. No data was saved.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        test_scraper()
    else:
        main()
