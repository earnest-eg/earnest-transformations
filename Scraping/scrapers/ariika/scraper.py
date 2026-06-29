import argparse
import csv
import html
import json
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


BASE_URL = "https://ariika.com"
TIMEZONE = "Africa/Cairo"
OUTPUT_DIR = Path("output")

TARGET_COLUMNS = [
    "title",
    "name",
    "product_current_price",
    "product_old_price",
    "product_discount",
    "product_url",
    "product_image_url",
    "product_seller",
    "product_availability",
    "product_category",
    "product_subcategory",
    "product_unit",
    "product_weight",
    "scraping_time",
    "timestamp_timezone",
    "product_brand",
    "product_ram",
    "product_storage",
]

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
IMAGE_NS = {"image": "http://www.google.com/schemas/sitemap-image/1.1"}
USER_AGENT = "Mozilla/5.0 (compatible; AriikaCatalogScraper/1.0; +https://ariika.com/robots.txt)"


def fetch_text(url, timeout=30, retries=5, delay=1.0):
    last_error = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            if attempt < retries - 1:
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After")
                    wait = int(retry_after) if retry_after and retry_after.isdigit() else 8 * (attempt + 1)
                else:
                    wait = delay * (attempt + 1)
                time.sleep(wait)
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def absolute_url(url):
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("//"):
        return "https:" + url
    return urljoin(BASE_URL, url)


def price_to_number(value):
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, str):
            cleaned = re.sub(r"[^\d.]", "", value)
            if not cleaned:
                return ""
            amount = float(cleaned)
        else:
            # Shopify .js uses integer cents, while products.json uses decimal strings.
            amount = int(value) / 100 if int(value) >= 10000 else float(value)
        return int(amount) if amount.is_integer() else round(amount, 2)
    except (TypeError, ValueError):
        return ""


def discount_percent(current_price, old_price):
    try:
        current = float(current_price)
        old = float(old_price)
    except (TypeError, ValueError):
        return ""
    if old <= current or old <= 0:
        return ""
    return round(((old - current) / old) * 100, 3)


def slug_from_url(url, prefix):
    path = urlparse(url).path.strip("/")
    if path.startswith(prefix + "/"):
        return path.split("/", 1)[1].strip("/")
    return path.rsplit("/", 1)[-1]


def title_from_handle(handle):
    return clean_text(handle.replace("-", " ").replace("_", " ").title())


def parse_sitemap_urls(xml_text):
    root = ET.fromstring(xml_text)
    return [node.text.strip() for node in root.findall(".//sm:loc", SITEMAP_NS) if node.text]


def parse_product_sitemap(xml_text):
    root = ET.fromstring(xml_text)
    products = {}
    for url_node in root.findall("sm:url", SITEMAP_NS):
        loc_node = url_node.find("sm:loc", SITEMAP_NS)
        if loc_node is None or not loc_node.text or "/products/" not in loc_node.text:
            continue
        product_url = loc_node.text.strip()
        handle = slug_from_url(product_url, "products")
        image_url = ""
        image_title = ""
        image_node = url_node.find("image:image", IMAGE_NS)
        if image_node is not None:
            loc = image_node.find("image:loc", IMAGE_NS)
            title = image_node.find("image:title", IMAGE_NS)
            image_url = loc.text.strip() if loc is not None and loc.text else ""
            image_title = clean_text(title.text) if title is not None and title.text else ""
        products[handle] = {
            "handle": handle,
            "url": product_url,
            "sitemap_image_url": image_url,
            "sitemap_title": image_title,
        }
    return products


def parse_collection_sitemap(xml_text):
    root = ET.fromstring(xml_text)
    collections = []
    seen = set()
    for url_node in root.findall("sm:url", SITEMAP_NS):
        loc_node = url_node.find("sm:loc", SITEMAP_NS)
        if loc_node is None or not loc_node.text or "/collections/" not in loc_node.text:
            continue
        url = loc_node.text.strip()
        handle = slug_from_url(url, "collections")
        if handle in seen:
            continue
        seen.add(handle)
        image_title = ""
        image_node = url_node.find("image:image", IMAGE_NS)
        if image_node is not None:
            title = image_node.find("image:title", IMAGE_NS)
            image_title = clean_text(title.text) if title is not None and title.text else ""
        collections.append(
            {
                "handle": handle,
                "url": url,
                "title": image_title or title_from_handle(handle),
                "status": "pending",
                "error": "",
                "products_found": 0,
            }
        )
    return collections


def discover_from_sitemaps():
    index = fetch_text(f"{BASE_URL}/sitemap.xml")
    sitemap_urls = parse_sitemap_urls(index)
    product_sitemaps = [url for url in sitemap_urls if "sitemap_products" in url and "/ar/" not in url]
    collection_sitemaps = [url for url in sitemap_urls if "sitemap_collections" in url and "/ar/" not in url]

    products = {}
    collections = []
    for sitemap_url in product_sitemaps:
        products.update(parse_product_sitemap(fetch_text(sitemap_url)))
    for sitemap_url in collection_sitemaps:
        collections.extend(parse_collection_sitemap(fetch_text(sitemap_url)))
    return products, collections


def collection_products_url(handle, page):
    return f"{BASE_URL}/collections/{handle}/products.json?limit=250&page={page}"


def discover_bulk_products(max_pages=200, delay=0.15):
    bulk_products = {}
    for page in range(1, max_pages + 1):
        payload = json.loads(fetch_text(f"{BASE_URL}/products.json?limit=250&page={page}"))
        items = payload.get("products", [])
        if not items:
            break
        for item in items:
            handle = item.get("handle", "")
            if handle:
                bulk_products[handle] = item
        time.sleep(delay)
    return bulk_products


def discover_collection_memberships(collections, products, max_pages=200, delay=0.15):
    memberships = {}
    for collection in collections:
        handle = collection["handle"]
        try:
            total = 0
            for page in range(1, max_pages + 1):
                payload = json.loads(fetch_text(collection_products_url(handle, page)))
                items = payload.get("products", [])
                if not items:
                    break
                for item in items:
                    product_handle = item.get("handle", "")
                    if not product_handle:
                        continue
                    total += 1
                    memberships.setdefault(product_handle, [])
                    if handle not in [entry["handle"] for entry in memberships[product_handle]]:
                        memberships[product_handle].append(
                            {
                                "handle": handle,
                                "title": collection["title"],
                                "url": collection["url"],
                            }
                        )
                    products.setdefault(
                        product_handle,
                        {
                            "handle": product_handle,
                            "url": f"{BASE_URL}/products/{product_handle}",
                            "sitemap_image_url": "",
                            "sitemap_title": clean_text(item.get("title", "")),
                        },
                    )
                time.sleep(delay)
            collection["products_found"] = total
            collection["status"] = "done"
        except Exception as exc:
            collection["status"] = "error"
            collection["error"] = str(exc)
    return memberships


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_todo_products(path):
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return {row["url"]: row for row in reader if row.get("url")}


def write_todos(products, memberships, collections, existing=None):
    existing = existing or {}
    category_rows = [
        {
            "url": item["url"],
            "category": item["title"],
            "handle": item["handle"],
            "status": item["status"],
            "products_found": item["products_found"],
            "error": item["error"],
        }
        for item in collections
    ]
    product_rows = []
    for handle, product in sorted(products.items()):
        cats = memberships.get(handle, [])
        category = " | ".join(cat["title"] for cat in cats)
        url = product["url"]
        old = existing.get(url, {})
        product_rows.append(
            {
                "url": url,
                "category": category,
                "handle": handle,
                "status": old.get("status", "pending"),
                "error": old.get("error", ""),
            }
        )
    write_csv(OUTPUT_DIR / "todo_categories.csv", category_rows, ["url", "category", "handle", "status", "products_found", "error"])
    write_csv(OUTPUT_DIR / "todo_products.csv", product_rows, ["url", "category", "handle", "status", "error"])


def fetch_product(handle):
    return json.loads(fetch_text(f"{BASE_URL}/products/{handle}.js"))


def first_nonempty(*values):
    for value in values:
        if value:
            return value
    return ""


def variant_image(variant, product, sitemap_image_url):
    image = variant.get("featured_image") or {}
    if isinstance(image, dict):
        return absolute_url(first_nonempty(image.get("src"), image.get("preview_image", {}).get("src") if isinstance(image.get("preview_image"), dict) else ""))
    featured = product.get("featured_image")
    images = product.get("images") or []
    first_image = ""
    if images:
        first = images[0]
        first_image = first.get("src", "") if isinstance(first, dict) else first
    return absolute_url(first_nonempty(featured, first_image, sitemap_image_url))


def normalize_name(title):
    value = clean_text(title)
    value = re.sub(r"\s+-\s+.*$", "", value)
    value = re.sub(r"\s*/\s*(black|white|grey|gray|blue|red|green|yellow|orange|pink|beige|brown|navy|mustard)\b.*$", "", value, flags=re.I)
    return value.strip() or clean_text(title)


def extract_unit(text):
    patterns = [
        r"\b(?:set of|pack of)\s+\d+\b",
        r"\b\d+\s*(?:pcs|pieces|piece|pc|pack|pairs?)\b",
        r"\b\d+(?:\.\d+)?\s*(?:l|ml|g|kg|cm|m)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(0)
    return ""


def extract_ram(text):
    match = re.search(r"\b\d+\s*GB\s*(?:RAM)?\b", text, flags=re.I)
    return match.group(0).replace(" ", "") if match and "ram" in text.lower() else ""


def extract_storage(text):
    match = re.search(r"\b\d+\s*(?:GB|TB)\s*(?:SSD|HDD|storage)?\b", text, flags=re.I)
    if match and any(word in text.lower() for word in ["ssd", "hdd", "storage"]):
        return re.sub(r"\s+", " ", match.group(0)).strip()
    return ""


def standardized_category(collection_title, product_type, tags, title=""):
    text = " ".join([collection_title, product_type, title, " ".join(tags)]).lower()
    mapping = [
        ("home > bedding", ["sheet", "duvet", "comforter", "mattress", "pillow", "bed", "bedding"]),
        ("home > bath", ["towel", "bath", "bathrobe"]),
        ("home > furniture", ["sofa", "chair", "table", "recliner", "bean bag", "seating", "furniture", "nightstand", "wardrobe", "crib"]),
        ("home > outdoor", ["outdoor", "garden", "beach", "floater", "floatable"]),
        ("home > kitchenware", ["kitchen", "dinner", "plate", "bowl", "glass", "cup", "mug", "cookware", "serveware", "tableware"]),
        ("home > decor", ["rug", "macrame", "vase", "planter", "basket", "candle", "lamp", "lighting", "decor", "wall"]),
        ("baby products", ["baby", "kids", "crib", "nursery"]),
        ("pet supplies", ["pet"]),
    ]
    for category, needles in mapping:
        if any(needle in text for needle in needles):
            return category
    return "home"


def weight_text(variant):
    grams = variant.get("weight", variant.get("grams"))
    try:
        grams = int(grams)
    except (TypeError, ValueError):
        return ""
    return f"{grams} g" if grams > 0 else ""


def build_rows_for_product(product, product_meta, memberships, category_mode):
    handle = product.get("handle") or product_meta["handle"]
    product_url_base = f"{BASE_URL}/products/{handle}"
    product_type = clean_text(product.get("type") or product.get("product_type") or "")
    product_categories = memberships.get(handle) or []
    if not product_categories:
        product_categories = [{"handle": "", "title": product_type or "Home", "url": ""}]
    if category_mode == "primary":
        product_categories = product_categories[:1]

    rows = []
    variants = product.get("variants") or [{}]
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    for variant in variants:
        current = price_to_number(variant.get("price", product.get("price")))
        old = price_to_number(variant.get("compare_at_price", product.get("compare_at_price")))
        if not current:
            continue
        variant_title = clean_text(variant.get("title") or variant.get("public_title", ""))
        base_title = clean_text(product.get("title") or product_meta.get("sitemap_title"))
        if variant_title and variant_title.lower() != "default title" and variant_title not in base_title:
            title = f"{base_title} - {variant_title}"
        else:
            title = clean_text(variant.get("name") or base_title)
        if not title:
            continue
        image_url = variant_image(variant, product, product_meta.get("sitemap_image_url", ""))
        if not image_url:
            continue
        public_title = clean_text(variant.get("public_title", ""))
        description = clean_text(product.get("description") or product.get("body_html") or "")
        combined_text = " ".join([title, public_title, description])
        for collection in product_categories:
            subcategory = clean_text(collection.get("title") or product_type)
            broad_category = standardized_category(subcategory, product_type, tags, title)
            url = product_url_base
            if variant.get("id"):
                url = f"{url}?variant={variant['id']}"
            rows.append(
                {
                    "title": title,
                    "name": normalize_name(product.get("title") or title),
                    "product_current_price": current,
                    "product_old_price": old,
                    "product_discount": discount_percent(current, old),
                    "product_url": url,
                    "product_image_url": image_url,
                    "product_seller": clean_text(product.get("vendor") or "ariika"),
                    "product_availability": "in_stock" if variant.get("available", product.get("available")) else "out_of_stock",
                    "product_category": broad_category,
                    "product_subcategory": subcategory,
                    "product_unit": extract_unit(combined_text),
                    "product_weight": weight_text(variant),
                    "scraping_time": datetime.now().isoformat(timespec="seconds"),
                    "timestamp_timezone": TIMEZONE,
                    "product_brand": clean_text(product.get("vendor") or "ariika"),
                    "product_ram": extract_ram(combined_text),
                    "product_storage": extract_storage(combined_text),
                }
            )
    return rows


def valid_row(row):
    if not row.get("title") or not row.get("product_url") or not row.get("product_current_price") or not row.get("product_image_url"):
        return False
    bad_values = {"undefined", "null", "none", "nan"}
    return not any(str(value).strip().lower() in bad_values for value in row.values())


def scrape_products(products, memberships, limit=None, category_mode="all", delay=0.2, product_cache=None):
    todo_path = OUTPUT_DIR / "todo_products.csv"
    todo = read_todo_products(todo_path)
    rows = []
    statuses = {}
    items = list(sorted(products.items()))
    if limit:
        items = items[:limit]
    for index, (handle, meta) in enumerate(items, start=1):
        url = meta["url"]
        try:
            product = product_cache.get(handle) if product_cache else None
            if product is None:
                product = fetch_product(handle)
            product_rows = [row for row in build_rows_for_product(product, meta, memberships, category_mode) if valid_row(row)]
            rows.extend(product_rows)
            statuses[url] = {"status": "done", "error": "", "rows": len(product_rows)}
        except Exception as exc:
            statuses[url] = {"status": "error", "error": str(exc), "rows": 0}
        if index % 25 == 0:
            print(f"scraped {index}/{len(items)} products, rows={len(rows)}", flush=True)
        time.sleep(delay)

    # Preserve the todo file and update status/error after scraping.
    updated = []
    with todo_path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            status = statuses.get(row["url"])
            if status:
                row["status"] = status["status"]
                row["error"] = status["error"]
            updated.append(row)
    write_csv(todo_path, updated, ["url", "category", "handle", "status", "error"])

    deduped = []
    seen = set()
    for row in rows:
        key = (row["product_url"], row["product_subcategory"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped, statuses


def validate_rows(rows):
    issues = []
    if TARGET_COLUMNS != TARGET_COLUMNS[:]:
        issues.append("internal column mismatch")
    for index, row in enumerate(rows, start=2):
        if set(row.keys()) != set(TARGET_COLUMNS):
            issues.append(f"row {index}: wrong columns")
        for field in ["product_current_price", "product_old_price", "product_discount"]:
            value = row.get(field)
            if value == "":
                continue
            try:
                float(value)
            except (TypeError, ValueError):
                issues.append(f"row {index}: {field} is not numeric")
        for field in ["product_url", "product_image_url"]:
            value = row.get(field, "")
            if value and not value.startswith(("http://", "https://")):
                issues.append(f"row {index}: {field} is not absolute")
    return issues


def archive_outputs(paths):
    zip_paths = []
    for source in paths:
        zip_path = source.with_suffix(source.suffix + ".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(source, arcname=source.name)
        zip_paths.append(zip_path)
    bundle_path = OUTPUT_DIR / "ariika_exports.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in paths:
            archive.write(source, arcname=source.name)
    zip_paths.append(bundle_path)
    return zip_paths


def main():
    parser = argparse.ArgumentParser(description="Scrape ariika.com Shopify catalog into the requested clean schema.")
    parser.add_argument("--limit", type=int, default=None, help="Limit product pages for testing.")
    parser.add_argument("--category-mode", choices=["all", "primary"], default="all", help="Emit all collection/product rows or only the first category.")
    parser.add_argument("--collection-limit", type=int, default=None, help="Limit collection loops for testing.")
    parser.add_argument("--bulk-page-limit", type=int, default=None, help="Limit products.json pages for testing.")
    parser.add_argument("--skip-collections", action="store_true", help="Use sitemap products only and skip collection membership loops.")
    parser.add_argument("--product-pages", action="store_true", help="Fetch each /products/{handle}.js page instead of the paginated products.json catalog.")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between product requests in seconds.")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    products, collections = discover_from_sitemaps()
    if args.collection_limit:
        collections = collections[: args.collection_limit]
    memberships = {}
    if not args.skip_collections:
        memberships = discover_collection_memberships(collections, products)
    product_cache = {}
    if not args.product_pages:
        product_cache = discover_bulk_products(max_pages=args.bulk_page_limit or 200)
        for handle, item in product_cache.items():
            products.setdefault(
                handle,
                {
                    "handle": handle,
                    "url": f"{BASE_URL}/products/{handle}",
                    "sitemap_image_url": "",
                    "sitemap_title": clean_text(item.get("title", "")),
                },
            )
    write_todos(products, memberships, collections, read_todo_products(OUTPUT_DIR / "todo_products.csv"))

    rows, statuses = scrape_products(products, memberships, limit=args.limit, category_mode=args.category_mode, delay=args.delay, product_cache=product_cache)
    issues = validate_rows(rows)

    csv_path = OUTPUT_DIR / "ariika_products_clean.csv"
    json_path = OUTPUT_DIR / "ariika_products_clean.json"
    write_csv(csv_path, rows, TARGET_COLUMNS)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_paths = archive_outputs([csv_path, json_path])

    report = {
        "scraping_time": datetime.now().isoformat(timespec="seconds"),
        "timestamp_timezone": TIMEZONE,
        "unique_product_pages_discovered": len(products),
        "bulk_product_records_loaded": len(product_cache),
        "collections_discovered": len(collections),
        "rows_exported": len(rows),
        "product_pages_done": sum(1 for item in statuses.values() if item["status"] == "done"),
        "product_pages_error": sum(1 for item in statuses.values() if item["status"] == "error"),
        "validation_issue_count": len(issues),
        "validation_issues_sample": issues[:50],
        "target_minimum_note": "The requested 100000 minimum cannot be guaranteed from a Shopify catalog if the live site exposes fewer products/variants/category memberships. This scraper exports the maximum discovered public rows.",
        "outputs": [str(csv_path), str(json_path)] + [str(path) for path in zip_paths],
    }
    (OUTPUT_DIR / "scrape_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
