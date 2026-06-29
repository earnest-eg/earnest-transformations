import asyncio
import aiohttp
import xml.etree.ElementTree as ET
import re
import csv
import json
import os
import time
from datetime import datetime, timezone

BASE_URL = "https://www.intersport.com.eg"
SITEMAP_PRODUCTS_1 = "https://www.intersport.com.eg/sitemap_products_1.xml?from=8246832267484&to=9373801939164"
SITEMAP_PRODUCTS_2 = "https://www.intersport.com.eg/sitemap_products_2.xml?from=9373801971932&to=9421317112028"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SCRAPING_TIME = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
TIMEZONE = "Africa/Cairo"

KNOWN_BRANDS = [
    "skechers", "anta", "energetics", "aerobird", "adidas", "nike", "puma",
    "wilson", "arena", "ipanema", "rider", "firefly", "dunlop", "mckinley",
    "pro touch", "body sculpture", "tecnifibre", "babolat", "trainetic",
    "zoya", "drop shot", "birkenstock", "crocs", "cubs", "spurt",
    "entercise", "head", "starvie", "bullpadel", "libra", "reef",
    "tempo", "seven performance", "umbro", "tecnopro", "marika",
    "intersport", "keep going", "fin", "hurley", "asics",
]

COLUMNS = [
    "title", "name", "product_current_price", "product_old_price",
    "product_discount", "product_url", "product_image_url",
    "product_seller", "product_availability", "product_category",
    "product_subcategory", "product_unit", "product_weight",
    "scraping_time", "timestamp_timezone", "product_brand",
    "product_ram", "product_storage"
]


class RateLimiter:
    def __init__(self, max_per_minute=40):
        self.max_per_minute = max_per_minute
        self.tokens = max_per_minute
        self.last_refill = time.monotonic()

    async def acquire(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_per_minute, self.tokens + elapsed * (self.max_per_minute / 60.0))
        self.last_refill = now
        if self.tokens < 1:
            wait = (1 - self.tokens) * (60.0 / self.max_per_minute)
            await asyncio.sleep(wait)
            self.tokens = 0
            self.last_refill = time.monotonic()
        else:
            self.tokens -= 1


async def fetch_sitemap(session, url):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        text = await resp.text()
    root = ET.fromstring(text)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "image": "http://www.google.com/schemas/sitemap-image/1.1"}
    products = []
    for url_elem in root.findall(".//s:url", ns):
        loc = url_elem.find("s:loc", ns)
        if loc is None:
            continue
        product_url = loc.text
        if not product_url.startswith(BASE_URL + "/products/"):
            continue
        image_elems = url_elem.findall(".//image:image/image:loc", ns)
        image_url = image_elems[0].text if image_elems else ""
        products.append({"url": product_url, "image_url": image_url})
    return products


async def fetch_product_json(session, product_url, limiter):
    json_url = product_url + ".json"
    for attempt in range(3):
        try:
            await limiter.acquire()
            async with session.get(json_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return data.get("product", {})
                elif resp.status == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                elif resp.status == 404:
                    return None
                else:
                    if attempt < 2:
                        await asyncio.sleep(1)
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError):
            if attempt < 2:
                await asyncio.sleep(2)
    return None


def extract_category_from_tags(tags):
    category = "sports > general"
    subcategory = ""
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    for tag in tag_list:
        tag_lower = tag.lower()
        if "default category/" in tag_lower:
            parts = tag_lower.replace("default category/", "").split("/")
            for part in parts:
                part = part.strip()
                if part in ("running", "fitness", "football", "basketball", "swimming", "tennis", "squash", "badminton", "padel", "golf", "yoga", "boxing", "handball", "volley", "volley ball"):
                    subcategory = subcategory or part
                    sport = part.replace("volley ball", "volleyball")
                    category = f"sports > {sport}"
                elif part in ("shoes", "accessories", "clothing", "equipment", "swimwear", "tops", "bottoms", "socks", "bags", "backpacks", "caps", "gloves", "bottles", "balls", "helmets"):
                    subcategory = subcategory or part
    return category, subcategory


def extract_brand(title, vendor, product_type):
    if vendor and vendor.lower() not in ("", "generic", "unknown", "intersport", "-"):
        return vendor.strip()
    title_lower = title.lower()
    for known_brand in KNOWN_BRANDS:
        if known_brand in title_lower:
            return known_brand.title()
    return ""


def extract_ram_storage(title):
    ram = ""
    storage = ""
    title_lower = title.lower()
    m = re.search(r'(\d+)\s*gb\s*ram', title_lower)
    if m:
        ram = f"{m.group(1)}GB"
    m = re.search(r'(\d+)\s*gb\s*(?:ssd|storage|rom)', title_lower)
    if m:
        storage = f"{m.group(1)}GB"
    if not storage and not ram:
        m = re.search(r'(\d+)\s*gb', title_lower)
        if m:
            val = int(m.group(1))
            if val <= 16:
                ram = f"{val}GB"
            elif val > 16:
                storage = f"{val}GB"
    return ram, storage


def extract_weight(grams, weight_val, weight_unit):
    if grams and grams > 0:
        if grams < 1000:
            return f"{grams} g"
        else:
            return f"{grams / 1000:.2f} kg"
    if weight_val and weight_val > 0:
        return f"{weight_val} {weight_unit}"
    return ""


def extract_unit(title):
    m = re.search(r'(\d+)\s*(pcs|pieces?|pack|pair|set)', title.lower())
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return ""


def get_availability(product_data):
    status = product_data.get("status", "")
    if status == "active":
        return "in_stock"
    published = product_data.get("published_at")
    if published:
        return "in_stock"
    return ""


def clean_price(price_str):
    if not price_str or price_str.strip() in ("", "0.00", "0"):
        return ""
    try:
        price = float(price_str)
        if price <= 0:
            return ""
        if price == int(price):
            return str(int(price))
        return f"{price:.2f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return ""


def calculate_discount(old_price, current_price):
    if not old_price or not current_price:
        return ""
    try:
        old = float(old_price)
        current = float(current_price)
        if old <= 0 or current <= 0 or current >= old:
            return ""
        discount = ((old - current) / old) * 100
        return f"{discount:.3f}%"
    except (ValueError, TypeError):
        return ""


def clean_title(title):
    return re.sub(r'\s+', ' ', title.strip())


def generate_name(title):
    name = re.sub(r',\s*(Black|White|Navy|Blue|Red|Green|Grey|Gray|Pink|Purple|Orange|Yellow|Brown|Beige|Olive|Teal|Coral|Mint|Lavender|Turquoise|Silver|Gold|Rose|Burgundy|Khaki|Cream|Tan|Peach|Maroon).*$', '', title, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip()
    return name if name else title


def process_product(product_info, product_data):
    if not product_data:
        return None
    url = product_info["url"]
    image_url = product_info.get("image_url", "")
    title = clean_title(product_data.get("title", ""))
    vendor = product_data.get("vendor", "")
    product_type = product_data.get("product_type", "")
    tags = product_data.get("tags", "")
    variants = product_data.get("variants", [])
    primary_variant = variants[0] if variants else {}
    current_price = clean_price(primary_variant.get("price", ""))
    old_price = clean_price(primary_variant.get("compare_at_price", ""))
    discount = calculate_discount(old_price, current_price)
    grams = primary_variant.get("grams", 0)
    weight_val = primary_variant.get("weight", 0)
    weight_unit = primary_variant.get("weight_unit", "kg")
    weight = extract_weight(grams, weight_val, weight_unit)
    category, subcategory = extract_category_from_tags(tags)
    if not image_url:
        images = product_data.get("images", [])
        if images:
            image_url = images[0].get("src", "")
    if not image_url:
        image_elem = product_data.get("image") or {}
        image_url = image_elem.get("src", "")
    brand = extract_brand(title, vendor, product_type)
    ram, storage = extract_ram_storage(title)
    availability = get_availability(product_data)
    unit = extract_unit(title)
    name = generate_name(title)
    return {
        "title": title, "name": name,
        "product_current_price": current_price, "product_old_price": old_price,
        "product_discount": discount, "product_url": url,
        "product_image_url": image_url, "product_seller": "INTERSPORT Egypt",
        "product_availability": availability, "product_category": category,
        "product_subcategory": subcategory, "product_unit": unit,
        "product_weight": weight, "scraping_time": SCRAPING_TIME,
        "timestamp_timezone": TIMEZONE, "product_brand": brand,
        "product_ram": ram, "product_storage": storage,
    }


def save_progress(rows, filename="intersport_products_partial.csv"):
    filepath = os.path.join(OUTPUT_DIR, filename)
    mode = "a" if os.path.exists(filepath) else "w"
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if mode == "w":
            writer.writeheader()
        writer.writerows(rows)


async def main():
    connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
    limiter = RateLimiter(max_per_minute=40)

    async with aiohttp.ClientSession(connector=connector) as session:
        print("[1/4] Fetching sitemaps...")
        sitemap_tasks = [
            fetch_sitemap(session, SITEMAP_PRODUCTS_1),
            fetch_sitemap(session, SITEMAP_PRODUCTS_2),
        ]
        results = await asyncio.gather(*sitemap_tasks)
        all_products = []
        for r in results:
            all_products.extend(r)

        total = len(all_products)
        print(f"[2/4] Found {total} products in sitemaps. Fetching details...")

        total_valid = 0
        batch_size = 40

        for i in range(0, total, batch_size):
            batch = all_products[i:i+batch_size]
            tasks = [fetch_product_json(session, p["url"], limiter) for p in batch]
            batch_json = await asyncio.gather(*tasks)

            batch_rows = []
            for idx, product_data in enumerate(batch_json):
                if product_data:
                    row = process_product(batch[idx], product_data)
                    if row:
                        batch_rows.append(row)

            if batch_rows:
                total_valid += len(batch_rows)
                save_progress(batch_rows)

            elapsed = time.monotonic()
            rate = total_valid / (elapsed / 60) if elapsed > 0 else 0
            pct = min(i + batch_size, total) / total * 100
            eta_min = ((total - (i + batch_size)) / max(rate, 0.1)) if rate > 0 else 999

            print(f"  [{pct:4.1f}%] {min(i+batch_size, total)}/{total} - {total_valid} valid, {rate:.1f} prod/min, ETA: {eta_min:.0f}min")

        print(f"[3/4] Valid products collected: {total_valid}")

        partial_path = os.path.join(OUTPUT_DIR, "intersport_products_partial.csv")
        csv_path = os.path.join(OUTPUT_DIR, "intersport_products.csv")
        json_path = os.path.join(OUTPUT_DIR, "intersport_products.json")

        if os.path.exists(partial_path):
            os.replace(partial_path, csv_path)

        all_rows = []
        if os.path.exists(csv_path):
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_rows = list(reader)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(all_rows, f, ensure_ascii=False, indent=2)

        print(f"[4/4] Final export: {len(all_rows)} products")
        print(f"      CSV: {csv_path}")
        print(f"      JSON: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
