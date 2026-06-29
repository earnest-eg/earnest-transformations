import csv
import io
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import requests


BASE_URL = "https://btech.com"
SITEMAP_URL = "https://btech.com/sitemap.xml"
OUTPUT_CSV = "btech_products_all_categories.csv"
PROGRESS_CSV = "btech_scrape_progress.csv"
TARGET_ROWS = 100000
PAGE_SIZE = 20
MAX_WORKERS = 12
REQUEST_TIMEOUT = 35
RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CSV_COLUMNS = [
    "title",
    "current_price",
    "old_price",
    "discount",
    "url",
    "category",
]

thread_local = threading.local()
write_lock = threading.Lock()


def session():
    if not hasattr(thread_local, "session"):
        s = requests.Session()
        s.headers.update(HEADERS)
        thread_local.session = s
    return thread_local.session


def request_text(url):
    last_error = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session().get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            last_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5 * attempt)
    raise RuntimeError(last_error)


def extract_json_object(s, start_idx):
    brace_depth = 0
    in_string = False
    escape = False
    start = -1

    for i in range(start_idx, len(s)):
        ch = s[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == "{":
                if brace_depth == 0:
                    start = i
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0 and start >= 0:
                    return s[start : i + 1]
    return None


def clean_json(s):
    result = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            next_ch = s[i + 1]
            if next_ch in '"\\/bfnrtu':
                result.append(ch)
                result.append(next_ch)
            else:
                result.append(next_ch)
            i += 2
            continue
        if ord(ch) < 32 and ch not in "\n\r\t":
            result.append(" ")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def unescape_rsc_block(block):
    return (
        block.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\/", "/")
        .replace("\\t", "\t")
    )


def parse_category_page(html):
    blocks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    total_count = 0
    products = []

    for block in blocks:
        unescaped = unescape_rsc_block(block)

        if total_count == 0:
            count_match = re.search(
                r'"children":\[(\d[\d,]*),\s*"\s*",\s*"results"\]', unescaped
            )
            if count_match:
                total_count = int(count_match.group(1).replace(",", ""))

        if '"items"' not in unescaped or '"data":' not in unescaped:
            continue

        data_idx = unescaped.find('"data":')
        data_json = extract_json_object(unescaped, data_idx + 7)
        if not data_json:
            continue

        try:
            data = json.loads(clean_json(data_json), strict=False)
        except json.JSONDecodeError:
            continue

        for page in data.get("pages", []):
            page_items = page.get("items", [])
            if page_items:
                products = page_items
                break

    return total_count, products


def category_name_from_url(url):
    parts = url.rstrip("/").split("/")
    slug_idx = parts.index("c")
    slugs = parts[slug_idx + 1 :]
    return " > ".join(slug.replace("-", " ").title() for slug in slugs)


def get_category_urls():
    print("Downloading sitemap...")
    text = requests.get(SITEMAP_URL, headers=HEADERS, timeout=60).text
    tree = ET.parse(io.StringIO(text))
    ns = {
        "ns": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "xhtml": "http://www.w3.org/1999/xhtml",
    }

    urls = []
    for url_elem in tree.findall(".//ns:url", ns):
        en_url = None
        for link in url_elem.findall("xhtml:link", ns):
            if link.get("hreflang") == "en":
                en_url = link.get("href")
                break
        if en_url and "/en/c/" in en_url:
            urls.append(en_url.rstrip("/"))

    # Scrape all categories, not only leaves. Parent categories contain products too,
    # and category-specific rows are required to approach the requested row count.
    return sorted(set(urls), key=lambda u: (u.count("/"), u))


def product_row(item, category_name):
    price = item.get("price") or {}
    current_price = price.get("final_price") or price.get("final_without_coupon") or 0
    old_price = price.get("base_price") or price.get("final_without_coupon") or current_price

    discount = 0
    if isinstance(current_price, (int, float)) and isinstance(old_price, (int, float)):
        if old_price > current_price and old_price:
            discount = round((1 - current_price / old_price) * 100)

    slug = item.get("slug") or item.get("variant_id") or item.get("product_id") or ""
    offer_id = item.get("offer_id") or item.get("offering_id") or ""
    url = f"{BASE_URL}/en/p/{slug}"
    if offer_id:
        url = f"{url}?offering_id={offer_id}"

    return {
        "title": item.get("name") or "",
        "current_price": current_price,
        "old_price": old_price,
        "discount": f"{discount}%",
        "url": url,
        "category": category_name,
    }


def fetch_category_metadata(category_url):
    html = request_text(category_url)
    total_count, products = parse_category_page(html)
    if total_count == 0 and products:
        total_count = len(products)
    return {
        "url": category_url,
        "category": category_name_from_url(category_url),
        "total_count": total_count,
        "pages": max(1, math.ceil(total_count / PAGE_SIZE)) if total_count else 1,
        "first_page_products": products,
    }


def fetch_page(category_url, page):
    url = category_url if page == 1 else f"{category_url}?page={page}"
    html = request_text(url)
    _, products = parse_category_page(html)
    return products


def load_done_pages():
    done = set()
    if not os.path.exists(PROGRESS_CSV):
        return done
    with open(PROGRESS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["category_url"], int(row["page"])))
    return done


def append_progress(category_url, page, rows):
    exists = os.path.exists(PROGRESS_CSV)
    with open(PROGRESS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["category_url", "page", "rows", "finished_at"])
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "category_url": category_url,
                "page": page,
                "rows": rows,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }
        )


def existing_row_count():
    if not os.path.exists(OUTPUT_CSV):
        return 0
    with open(OUTPUT_CSV, newline="", encoding="utf-8-sig") as f:
        return max(0, sum(1 for _ in f) - 1)


def ensure_output_header():
    if os.path.exists(OUTPUT_CSV) and os.path.getsize(OUTPUT_CSV) > 0:
        return
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()


def scrape_task(task):
    category_url, category_name, page = task
    products = fetch_page(category_url, page)
    rows = [product_row(item, category_name) for item in products]
    return category_url, page, rows


def main():
    ensure_output_header()
    done_pages = load_done_pages()
    start_rows = existing_row_count()

    categories = get_category_urls()
    print(f"Categories found: {len(categories)}")
    print(f"Existing rows: {start_rows}")
    print(f"Completed pages from checkpoint: {len(done_pages)}")

    print("Fetching category counts...")
    metadata = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_category_metadata, url): url for url in categories}
        for idx, future in enumerate(as_completed(futures), 1):
            url = futures[future]
            try:
                item = future.result()
                metadata.append(item)
                print(
                    f"[{idx}/{len(categories)}] {item['category']}: "
                    f"{item['total_count']} products, {item['pages']} pages"
                )
            except Exception as exc:
                print(f"[{idx}/{len(categories)}] FAILED {url}: {exc}")

    tasks = []
    for item in metadata:
        for page in range(1, item["pages"] + 1):
            key = (item["url"], page)
            if key not in done_pages:
                tasks.append((item["url"], item["category"], page))

    estimated_rows = sum(item["total_count"] for item in metadata)
    print(f"Estimated category rows available: {estimated_rows}")
    print(f"Remaining pages to scrape: {len(tasks)}")

    total_rows = start_rows
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(scrape_task, task): task for task in tasks}
            for idx, future in enumerate(as_completed(futures), 1):
                category_url, page = futures[future][0], futures[future][2]
                try:
                    category_url, page, rows = future.result()
                except Exception as exc:
                    print(f"[{idx}/{len(tasks)}] FAILED {category_url}?page={page}: {exc}")
                    continue

                with write_lock:
                    writer.writerows(rows)
                    f.flush()
                    append_progress(category_url, page, len(rows))
                    total_rows += len(rows)

                if idx % 25 == 0 or total_rows >= TARGET_ROWS:
                    print(f"[{idx}/{len(tasks)}] rows={total_rows}")

                if total_rows >= TARGET_ROWS:
                    print(f"Target reached: {total_rows} rows")
                    break

    print(f"Done. Rows written: {total_rows}")
    print(f"Output: {os.path.abspath(OUTPUT_CSV)}")
    if total_rows < TARGET_ROWS:
        print(
            f"WARNING: scraped all discovered category pages but only found {total_rows} rows. "
            f"The site appears to expose fewer than {TARGET_ROWS} category product rows."
        )


if __name__ == "__main__":
    main()
