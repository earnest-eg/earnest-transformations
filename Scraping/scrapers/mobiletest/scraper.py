"""
Instashop Product Scraper.

Scrapes product data from Instashop's public API across all available
places/stores, categories, and subcategories.

Usage:
    py src/instashop_scraper.py

Config:
    config/instashop_config.json  (copy from instashop_config.example.json)
"""

import csv
import json
import logging
import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).resolve().parent.parent / "logs" / "instashop_scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data" / "processed"
EXPORTS_DIR = PROJECT_ROOT / "exports"

DEFAULT_CONFIG_PATH = CONFIG_DIR / "instashop_config.json"
EXAMPLE_CONFIG_PATH = CONFIG_DIR / "instashop_config.example.json"

OUTPUT_COLUMNS = [
    "title", "current_price", "old_price", "discount", "url",
    "category", "subcategory", "name", "color", "Specifications",
    "img_URL", "time", "place",
]


def load_config(path: Path = None) -> dict:
    if path is None:
        path = DEFAULT_CONFIG_PATH
    if not path.exists():
        log.warning("Config not found: %s", path)
        if EXAMPLE_CONFIG_PATH.exists():
            log.warning("Copy the example config: cp config/instashop_config.example.json config/instashop_config.json")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_csv(rows, path: Path, fieldnames: list = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames or OUTPUT_COLUMNS)
        return
    fn = fieldnames or rows[0].keys()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fn)
        writer.writeheader()
        writer.writerows(rows)


def safe_request(session, method, url, config, **kwargs):
    target = config.get("target", {})
    max_retries = target.get("max_retries", 3)
    timeout = target.get("request_timeout", 30)
    delay_min = target.get("delay_min", 0.5)
    delay_max = target.get("delay_max", 2.0)

    for attempt in range(1, max_retries + 1):
        try:
            delay = random.uniform(delay_min, delay_max)
            time.sleep(delay)
            resp = session.request(method, url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            if attempt < max_retries:
                log.warning("HTTP error %s on %s (attempt %d/%d)", e, url, attempt, max_retries)
                time.sleep(2 ** attempt)
            else:
                log.error("Failed after %d retries: %s %s", max_retries, url, e)
                return None
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries:
                log.warning("Net error %s on %s (attempt %d/%d)", e, url, attempt, max_retries)
                time.sleep(2 ** attempt)
            else:
                log.error("Failed after %d retries: %s %s", max_retries, url, e)
                return None
    return None


def normalize_product(product: dict, place: str = "", category: str = "", subcategory: str = "") -> dict:
    def g(*keys, default=""):
        d = product
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k, {})
            else:
                return default
        return d if not isinstance(d, dict) else default

    title = (g("title") or g("name") or g("product_name") or "")
    name = (g("name") or title or "")
    current_price = (g("price") or g("current_price") or g("sale_price") or "")
    old_price = (g("old_price") or g("original_price") or g("regular_price") or "")
    try:
        cur = float(current_price) if current_price else 0
        old = float(old_price) if old_price else 0
        discount = round((1 - cur / old) * 100, 1) if old and cur and old > cur else ""
    except (ValueError, TypeError):
        discount = ""
    url = (g("url") or g("link") or g("product_url") or "")
    if url and not url.startswith("http"):
        url = urljoin("https://instashop.ae", url.lstrip("/"))
    product_id = (g("id") or g("product_id") or g("sku") or "")
    img = (g("image") or g("img") or g("thumbnail") or g("img_URL") or "")
    if img and not img.startswith("http"):
        img = urljoin("https:", img) if img.startswith("//") else img
    color = (g("color") or g("colour") or "")
    specs = (g("specifications") or g("Specifications") or g("description") or "")
    time_field = (g("time") or g("created_at") or g("updated_at") or "")
    place_val = (g("place") or g("store") or g("vendor") or place or "")
    category_val = (g("category") or category or "")
    subcategory_val = (g("subcategory") or subcategory or "")

    return {
        "title": str(title),
        "current_price": str(current_price),
        "old_price": str(old_price),
        "discount": str(discount),
        "url": str(url),
        "category": str(category_val),
        "subcategory": str(subcategory_val),
        "name": str(name),
        "color": str(color),
        "Specifications": str(specs),
        "img_URL": str(img),
        "time": str(time_field),
        "place": str(place_val),
        "_id": str(product_id) or str(url) or (str(title) + str(current_price) + str(img)),
    }


def extract_field(data, path):
    """Navigate a nested dict/list using a dot-separated path or list of keys."""
    if isinstance(path, str):
        path = [p for p in path.split(".") if p]
    current = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list):
            return current
        else:
            return None
    return current


class InstashopScraper:
    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(config.get("api", {}).get("headers", {}))

        self.api = config.get("api", {})
        self.pagi = config.get("pagination", {})
        self.targ = config.get("target", {})

        self.all_products = []
        self.all_places = []
        self.all_categories = []
        self.all_subcategories = []
        self.duplicates_removed = []
        self.total_before_dedupe = 0

        self.checkpoint_path = PROJECT_ROOT / self.config.get("output", {}).get("checkpoint_json", DATA_DIR / "instashop_checkpoint.json")
        self.places_csv = PROJECT_ROOT / self.config.get("output", {}).get("places_csv", DATA_DIR / "instashop_places.csv")
        self.categories_csv = PROJECT_ROOT / self.config.get("output", {}).get("categories_csv", DATA_DIR / "instashop_categories.csv")
        self.subcategories_csv = PROJECT_ROOT / self.config.get("output", {}).get("subcategories_csv", DATA_DIR / "instashop_subcategories.csv")
        self.products_csv = PROJECT_ROOT / self.config.get("output", {}).get("products_csv", EXPORTS_DIR / "instashop_products.csv")
        self.duplicates_csv = PROJECT_ROOT / self.config.get("output", {}).get("duplicates_csv", DATA_DIR / "instashop_duplicates_removed.csv")
        self.summary_csv = PROJECT_ROOT / self.config.get("output", {}).get("summary_csv", DATA_DIR / "instashop_scrape_summary.csv")

    def load_checkpoint(self):
        cp = load_json(self.checkpoint_path)
        if cp:
            self.all_products = cp.get("products", [])
            self.all_places = cp.get("places", [])
            self.all_categories = cp.get("categories", [])
            self.all_subcategories = cp.get("subcategories", [])
            self.duplicates_removed = cp.get("duplicates_removed", [])
            log.info("Loaded checkpoint: %d products, %d places, %d categories",
                     len(self.all_products), len(self.all_places), len(self.all_categories))
            return cp
        return None

    def save_checkpoint(self, state: dict = None):
        cp = {
            "products": self.all_products,
            "places": self.all_places,
            "categories": self.all_categories,
            "subcategories": self.all_subcategories,
            "duplicates_removed": self.duplicates_removed,
        }
        if state:
            cp.update(state)
        save_json(cp, self.checkpoint_path)
        log.info("Checkpoint saved (%d products)", len(self.all_products))

    def discover_places(self) -> list:
        endpoint = self.api.get("places_endpoint") or self.config.get("places", {}).get("endpoint")
        if not endpoint:
            log.info("No places endpoint configured, using single default place")
            return [{"id": "default", "name": "Default"}]

        base = self.api.get("base_url", "")
        url = urljoin(base, endpoint.lstrip("/"))
        log.info("Discovering places/stores from %s", url)
        resp = safe_request(self.session, "GET", url, self.config)
        if resp is None:
            log.warning("Could not fetch places, using default")
            return [{"id": "default", "name": "Default"}]

        try:
            data = resp.json()
            path = self.api.get("response_place_path", ["data", "stores"])
            places = extract_field(data, path) or data.get("stores") or data.get("data") or []
            if isinstance(places, dict):
                places = list(places.values())
            log.info("Found %d places/stores", len(places) if isinstance(places, list) else 0)
            return places if isinstance(places, list) else []
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            log.warning("Failed to parse places: %s", e)
            return [{"id": "default", "name": "Default"}]

    def discover_categories(self, place_id: str = None) -> list:
        endpoint = self.api.get("categories_endpoint")
        if not endpoint:
            return []

        base = self.api.get("base_url", "")
        url = urljoin(base, endpoint.lstrip("/"))
        params = {}
        place_param = self.config.get("places", {}).get("param_name", "store_id")
        if place_id and place_id != "default":
            params[place_param] = place_id

        resp = safe_request(self.session, "GET", url, self.config, params=params)
        if resp is None:
            return []

        try:
            data = resp.json()
            path = self.api.get("response_category_path", ["data", "categories"])
            cats = extract_field(data, path) or data.get("categories") or data.get("data") or []
            if isinstance(cats, dict):
                cats = list(cats.values())
            log.info("Found %d categories (place=%s)", len(cats) if isinstance(cats, list) else 0, place_id or "default")
            return cats if isinstance(cats, list) else []
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            log.warning("Failed to parse categories: %s", e)
            return []

    def fetch_products(self, place: dict, category: dict, subcategory: dict = None) -> list:
        endpoint = self.api.get("products_endpoint")
        if not endpoint:
            return []

        base = self.api.get("base_url", "")
        url = urljoin(base, endpoint.lstrip("/"))
        method = self.api.get("http_method", "GET")
        payload = self.api.get("payload")

        pt = self.pagi
        page = pt.get("start", 1)
        max_pages = pt.get("max_pages", 1000)
        stop = pt.get("stop_condition", "empty")
        limit = pt.get("limit", 50)
        page_param = pt.get("param", "page")
        place_param = self.config.get("places", {}).get("param_name", "store_id")

        products = []
        consecutive_empty = 0

        for pagenum in range(page, page + max_pages):
            params = {page_param: pagenum}
            if pt.get("type") == "offset":
                params[page_param] = (pagenum - 1) * limit
            if place and place.get("id") and place["id"] != "default":
                params[place_param] = place["id"]
            if category and category.get("id"):
                params["category_id"] = category["id"]
            if subcategory and subcategory.get("id"):
                params["subcategory_id"] = subcategory["id"]

            req_kwargs = {"params": params}
            if payload:
                body = dict(payload)
                body.update(params)
                req_kwargs["json"] = body

            resp = safe_request(self.session, method, url, self.config, **req_kwargs)
            if resp is None:
                break

            try:
                data = resp.json()
            except json.JSONDecodeError:
                log.warning("Non-JSON response on page %d", pagenum)
                break

            path = self.api.get("response_product_path", ["data", "products"])
            page_products = extract_field(data, path) or data.get("products") or data.get("data") or data.get("items") or []

            if isinstance(page_products, dict):
                page_products = list(page_products.values())

            if not page_products or (isinstance(page_products, list) and len(page_products) == 0):
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
                continue

            consecutive_empty = 0
            for p in page_products:
                if isinstance(p, dict):
                    products.append(p)

            log.info("  Page %d: %d items", pagenum, len(page_products))

            # Check has_more / cursor pagination
            if pt.get("has_more_field"):
                has_more = extract_field(data, pt["has_more_field"])
                if has_more is False:
                    break
            if pt.get("cursor_field"):
                cursor = extract_field(data, pt["cursor_field"])
                if not cursor:
                    break

        return products

    def deduplicate(self, products: list) -> list:
        seen = set()
        unique = []
        removed = []
        id_field = self.api.get("response_product_id_field", "id")
        url_field = self.api.get("response_product_url_field", "url")

        for p in products:
            pk = p.get("_id", p.get(id_field) or p.get(url_field) or "")
            if not pk:
                pk = p.get("title", "") + str(p.get("current_price", "")) + p.get("img_URL", "")
            if pk and pk not in seen:
                seen.add(pk)
                unique.append(p)
            elif pk:
                removed.append(p)

        self.duplicates_removed = removed
        return unique

    def run(self):
        log.info("=" * 60)
        log.info("Instashop Scraper")
        log.info("=" * 60)

        # Load checkpoint
        cp = self.load_checkpoint()
        if cp:
            done_places = set(cp.get("done_places", []))
            done_categories = set(cp.get("done_categories", []))
            done_subcategories = set(cp.get("done_subcategories", []))
        else:
            done_places = set()
            done_categories = set()
            done_subcategories = set()

        min_rows = self.targ.get("min_rows", 50000)

        # Discover places
        if not self.all_places:
            self.all_places = self.discover_places()
            save_csv(self.all_places, self.places_csv, fieldnames=["id", "name"])

        # For each place, discover categories and products
        for place in self.all_places:
            if len(self.all_products) >= min_rows:
                log.info("Reached target %d products, stopping place discovery", min_rows)
                break

            place_id = str(place.get("id", "")) or str(place.get("name", ""))
            if place_id in done_places:
                log.info("Skipping already-done place: %s", place.get("name", place_id))
                continue

            place_name = place.get("name") or place.get("title") or place_id
            log.info("\n--- Processing place: %s ---", place_name)

            # Discover categories for this place
            categories = self.discover_categories(place_id)
            for cat in categories:
                cat_id = str(cat.get("id", ""))
                if cat_id and cat_id in done_categories:
                    continue
                if len(self.all_products) >= min_rows:
                    break

                cat_name = cat.get("name") or cat.get("title") or cat_id
                log.info("  Category: %s", cat_name)

                # Try to get subcategories
                subcategories = cat.get("subcategories") or cat.get("children") or []
                if isinstance(subcategories, dict):
                    subcategories = list(subcategories.values())

                if subcategories:
                    for subcat in subcategories:
                        sub_id = str(subcat.get("id", ""))
                        if sub_id and sub_id in done_subcategories:
                            continue
                        if len(self.all_products) >= min_rows:
                            break
                        sub_name = subcat.get("name") or subcat.get("title") or sub_id
                        log.info("    Subcategory: %s", sub_name)

                        # Fetch products for this combination
                        prods = self.fetch_products(place, cat, subcat)
                        normalized = [normalize_product(p, place_name, cat_name, sub_name) for p in prods]
                        self.all_products.extend(normalized)
                        self.total_before_dedupe += len(normalized)
                        log.info("    Got %d products (total: %d)", len(normalized), len(self.all_products))

                        done_subcategories.add(sub_id)
                        self.save_checkpoint({"done_subcategories": list(done_subcategories),
                                              "done_categories": list(done_categories),
                                              "done_places": list(done_places)})
                else:
                    # No subcategories, fetch products for category directly
                    prods = self.fetch_products(place, cat)
                    normalized = [normalize_product(p, place_name, cat_name, "") for p in prods]
                    self.all_products.extend(normalized)
                    self.total_before_dedupe += len(normalized)
                    log.info("    Got %d products (total: %d)", len(normalized), len(self.all_products))

                if cat_id:
                    done_categories.add(cat_id)
                self.save_checkpoint({"done_subcategories": list(done_subcategories),
                                      "done_categories": list(done_categories),
                                      "done_places": list(done_places)})

            done_places.add(place_id)
            self.save_checkpoint({"done_places": list(done_places),
                                  "done_categories": list(done_categories),
                                  "done_subcategories": list(done_subcategories)})

        # Deduplicate
        log.info("\n--- Deduplication ---")
        log.info("Products before dedupe: %d", len(self.all_products))
        unique = self.deduplicate(self.all_products)
        log.info("Products after dedupe: %d", len(unique))
        log.info("Duplicates removed: %d", len(self.duplicates_removed))

        # Save outputs
        save_csv(unique, self.products_csv)
        save_csv(self.duplicates_removed, self.duplicates_csv)

        # Save summary
        reached = len(unique) >= min_rows
        summary = [{
            "total_places": len(self.all_places),
            "total_categories": len(self.all_categories) or len(done_categories),
            "total_subcategories": len(self.all_subcategories) or len(done_subcategories),
            "products_before_dedupe": len(self.all_products),
            "products_after_dedupe": len(unique),
            "duplicates_removed": len(self.duplicates_removed),
            "target_min_rows": min_rows,
            "target_reached": str(reached),
            "output_file": str(self.products_csv),
        }]
        save_csv(summary, self.summary_csv)

        # Print final summary
        log.info("\n" + "=" * 60)
        log.info("SCRAPE COMPLETE")
        log.info("=" * 60)
        log.info("  Places/stores scraped:  %d", len(self.all_places))
        log.info("  Categories:             %d", len(self.all_categories) or len(done_categories))
        log.info("  Subcategories:          %d", len(self.all_subcategories) or len(done_subcategories))
        log.info("  Products before dedupe: %d", self.total_before_dedupe or len(self.all_products))
        log.info("  Products after dedupe:  %d", len(unique))
        log.info("  Duplicates removed:     %d", len(self.duplicates_removed))
        log.info("  Target %d reached:      %s", min_rows, "YES" if reached else "NO")
        log.info("  Output:                 %s", self.products_csv)
        log.info("=" * 60)

        return {
            "places": len(self.all_places),
            "categories": len(self.all_categories) or len(done_categories),
            "subcategories": len(self.all_subcategories) or len(done_subcategories),
            "before_dedupe": len(self.all_products),
            "after_dedupe": len(unique),
            "duplicates": len(self.duplicates_removed),
            "target_reached": reached,
            "output_path": str(self.products_csv),
        }


def main():
    config = load_config()
    if not config:
        log.error("No config found. Create config/instashop_config.json from the example.")
        return

    scraper = InstashopScraper(config)
    scraper.run()


if __name__ == "__main__":
    main()
