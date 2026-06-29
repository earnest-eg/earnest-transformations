import requests
import json
import csv
import re
import os
import sys
import concurrent.futures
from datetime import datetime, timezone
from urllib.parse import urljoin

BASE_URL = "https://thebeautysecrets.com"
API_URL = "https://thebeautysecrets.com/api/v1/products"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
}

session = requests.Session()
session.headers.update(HEADERS)

OUTPUT_DIR = "B:/depi/scraping/The beauty/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

SCRAPING_TIME = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
TIMEZONE = "Africa/Cairo"
SELLER = "The Beauty Secrets"

def get_all_products_from_api():
    all_products = []
    page = 1
    total_pages = 999
    while page <= total_pages:
        url = f"{API_URL}/?page={page}&page_size=100"
        print(f"Fetching API page {page}...")
        try:
            r = session.get(url, timeout=30)
            if r.status_code != 200:
                print(f"  Error: HTTP {r.status_code}")
                break
            data = r.json()
            results = data.get("results", [])
            all_products.extend(results)
            total_pages = data.get("pages_count", 1)
            print(f"  Got {len(results)} (total: {len(all_products)}/{data.get('count', 0)})")
            page += 1
        except Exception as e:
            print(f"  Error: {e}")
            break
    return all_products

def extract_json_ld(html):
    pattern = r'<script type="application/ld\+json">(.*?)</script>'
    matches = re.findall(pattern, html, re.DOTALL)
    for match in matches:
        try:
            data = json.loads(match)
            if isinstance(data, dict) and data.get("@type") == "Product":
                return data
        except:
            continue
    return None

def extract_meta(html, prop):
    p1 = re.search(r'<meta[^>]+property="' + prop + r'"[^>]+content="([^"]*)"', html)
    if p1: return p1.group(1)
    p2 = re.search(r'<meta[^>]+name="' + prop + r'"[^>]+content="([^"]*)"', html)
    if p2: return p2.group(1)
    return None

def scrape_single(url):
    try:
        en_url = url.replace("https://thebeautysecrets.com/", "https://thebeautysecrets.com/en/").replace("/en//en/", "/en/")
        r = session.get(en_url, timeout=20)
        if r.status_code != 200:
            r = session.get(url, timeout=20)
        if r.status_code != 200:
            return url, None
        html = r.text
        json_ld = extract_json_ld(html)
        og_title = extract_meta(html, "og:title")
        og_image = extract_meta(html, "og:image")
        meta_brand = extract_meta(html, "product:brand")
        meta_price = extract_meta(html, "product:price:amount")
        meta_sale = extract_meta(html, "product:sale_price:amount")
        meta_avail = extract_meta(html, "product:availability")
        return url, {
            "json_ld": json_ld,
            "og_title": og_title if og_title else None,
            "og_image": og_image,
            "brand": meta_brand,
            "price": meta_price,
            "sale_price": meta_sale,
            "availability": meta_avail,
        }
    except Exception as e:
        return url, None

def clean_price(v):
    if v is None: return None
    v = re.sub(r'[^\d.]', '', str(v))
    try: return round(float(v), 2)
    except: return None

def extract_unit_weight(text):
    if not text: return ("", "")
    unit, weight = "", ""
    patterns = [
        (r'(\d+(?:\.\d+)?)\s*ml', 'ml'),
        (r'(\d+(?:\.\d+)?)\s*ML', 'ml'),
        (r'(\d+(?:\.\d+)?)\s*g\b', 'g'),
        (r'(\d+(?:\.\d+)?)\s*G\b', 'g'),
        (r'(\d+(?:\.\d+)?)\s*kg', 'kg'),
        (r'(\d+(?:\.\d+)?)\s*l\b', 'l'),
        (r'(\d+(?:\.\d+)?)\s*ounce', 'ounce'),
        (r'(\d+(?:\.\d+)?)\s*oz', 'oz'),
        (r'(\d+(?:\.\d+)?)\s*pcs', 'pcs'),
        (r'(\d+)\s*x\s*(\d+)\s*(ml|g|pcs)', 'multi'),
    ]
    for pattern, unit_type in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if unit_type == 'multi':
                v1, v2, u = match.group(1), match.group(2), match.group(3)
                unit = f"{v1}x{v2} {u}"
                weight = f"{int(v1)*int(v2)} {u}"
            else:
                unit = f"{match.group(1)} {unit_type}"
                weight = f"{match.group(1)} {unit_type}"
            break
    return unit, weight

def get_category_hierarchy(categories):
    if not categories:
        return "", ""
    names = [c.get("name", "") for c in categories if isinstance(c, dict)]
    if not names:
        return "", ""
    return (names[0], " > ".join(names[1:])) if len(names) > 1 else (names[0], "")

def map_category(main_cat, sub_cat):
    text = (main_cat + " " + sub_cat).lower()
    if any(w in text for w in ["perfume", "عطر", "fragrance", "عطور", "cologne", "كولونيا", "eau de", "body spray", "معطر جسم"]):
        return "beauty > perfumes"
    if any(w in text for w in ["body care", "body lotion", "shower gel", "body butter", "body scrub", "deodorant", "hand cream", "hand soap", "soap bar", "body wash", "lotion", "جل استحمام", "لوشن", "كريم", "صابون", "مرطب", "hand care", "hand"]):
        return "beauty > body care"
    if any(w in text for w in ["hair", "شعر", "شامبو", "بلسم"]):
        return "beauty > hair care"
    if any(w in text for w in ["candle", "شمع"]):
        return "home > candles"
    if any(w in text for w in ["room spray", "diffuser", "home", "معطر جو", "معطر منزل"]):
        return "home > home fragrance"
    if any(w in text for w in ["gift", "هدية", "هدايا", "مجموعة", "set"]):
        return "beauty > gift sets"
    if any(w in text for w in ["mask", "skin", "nail", "brush", "accessories", "ماسك", "اكسسوارات"]):
        return "beauty > accessories"
    if any(w in text for w in ["premium", "فاخرة"]):
        return "beauty > premium"
    return "beauty > other"

def process_product(api_prod, enrichment=None):
    name = api_prod.get("name", "")
    slug = api_prod.get("slug", "")
    price = api_prod.get("price")          # original/list price
    sale_price = api_prod.get("sale_price")  # current/discounted price
    eff_price = api_prod.get("effective_price")
    discount = api_prod.get("discount_percentage", 0)
    in_stock = api_prod.get("in_stock", False)
    html_url = api_prod.get("html_url", "")
    main_image = api_prod.get("main_image", {})
    image_url = ""
    if isinstance(main_image, dict):
        img = main_image.get("image", "")
        if isinstance(img, str):
            image_url = img
        elif isinstance(img, dict):
            image_url = img.get("url", "")
    w = api_prod.get("weight", {})
    weight_str = f"{w.get('value', '')} {w.get('unit', '')}".strip() if isinstance(w, dict) else ""
    categories = api_prod.get("categories", [])
    short_desc = api_prod.get("short_description", "")

    main_cat, sub_cat = get_category_hierarchy(categories)
    standard_cat = map_category(main_cat, sub_cat)
    if not sub_cat:
        sub_cat = main_cat

    # Try enrichment for English title
    title = name  # will use Arabic as fallback
    pname = name
    if enrichment:
        if enrichment.get("og_title"):
            title = enrichment["og_title"]

    # ----- PRICE LOGIC -----
    # API: price=original, sale_price=current(if discounted), effective_price=current
    # When discounted: price > sale_price == effective_price
    # When not discounted: price == effective_price, sale_price is None
    cur_price = clean_price(sale_price) if sale_price and float(sale_price) > 0 else None
    if not cur_price:
        cur_price = clean_price(eff_price or price)
    
    # Old price is the original price ONLY if there's a valid discounted price
    old_p = None
    sale_val = float(sale_price) if sale_price else 0
    price_val = float(price) if price else 0
    if sale_val > 0 and price_val > sale_val:
        old_p = clean_price(price)

    # Enrichment overrides
    if enrichment:
        if enrichment.get("og_image"):
            image_url = enrichment["og_image"]
        e_price = enrichment.get("price")
        e_sale = enrichment.get("sale_price")
        # If enrichment has sale_price, use it as old price
        if e_sale and e_sale.strip():
            cp = clean_price(e_sale)
            if cp and cp > 0 and cp > (cur_price or 0):
                old_p = cp
        # Use enrichment price as current if we don't have one
        if not cur_price and e_price:
            cur_price = clean_price(e_price)

    # Calculate discount
    calc_discount = ""
    if old_p and cur_price and old_p > cur_price:
        calc_discount = round(((old_p - cur_price) / old_p) * 100, 3)

    # Brand
    brand = "The Beauty Secrets"
    if enrichment and enrichment.get("brand"):
        brand = enrichment["brand"]

    # Availability
    avail = "in_stock" if in_stock else "out_of_stock"
    if enrichment and enrichment.get("availability"):
        a = enrichment["availability"]
        if "out" in a.lower():
            avail = "out_of_stock"

    if image_url and not image_url.startswith("http"):
        image_url = urljoin(BASE_URL, image_url)

    # Unit / weight from short_description (Arabic/HTML)
    unit, weight = extract_unit_weight(short_desc)
    if not unit:
        u2, w2 = extract_unit_weight(title)
        unit = unit or u2
        weight = weight or w2
    if not weight and weight_str:
        weight = weight_str
    # Also check slug for unit info
    if not unit:
        u3, w3 = extract_unit_weight(slug)
        unit = unit or u3
        weight = weight or w3

    return {
        "title": title,
        "name": pname,
        "product_current_price": cur_price if cur_price else "",
        "product_old_price": old_p if old_p else "",
        "product_discount": calc_discount,
        "product_url": html_url,
        "product_image_url": image_url,
        "product_seller": SELLER,
        "product_availability": avail,
        "product_category": standard_cat,
        "product_subcategory": sub_cat,
        "product_unit": unit,
        "product_weight": weight,
        "scraping_time": SCRAPING_TIME,
        "timestamp_timezone": TIMEZONE,
        "product_brand": brand,
        "product_ram": "",
        "product_storage": "",
    }

def main():
    print("=" * 60)
    print("THE BEAUTY SECRETS SCRAPER (FAST MODE)")
    print(f"Time: {SCRAPING_TIME}")
    print("=" * 60)

    # Step 1: Get all products from API
    print("\n[1] Fetching all products from API...")
    api_products = get_all_products_from_api()
    print(f"Total: {len(api_products)}")

    # Step 2: Scrape individual pages in parallel
    print(f"\n[2] Scraping {len(api_products)} product pages (parallel)...")
    urls = [p.get("html_url", "") for p in api_products if p.get("html_url")]
    enrichments = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        fut_to_url = {executor.submit(scrape_single, url): url for url in urls}
        done = 0
        for future in concurrent.futures.as_completed(fut_to_url):
            url, result = future.result()
            enrichments[url] = result
            done += 1
            if done % 50 == 0:
                print(f"  Scraped: {done}/{len(urls)}")

    # Step 3: Process
    print("\n[3] Processing data...")
    rows = []
    for p in api_products:
        url = p.get("html_url", "")
        enrich = enrichments.get(url)
        rows.append(process_product(p, enrich))

    # Step 4: Write CSV
    cols = [
        "title", "name", "product_current_price", "product_old_price",
        "product_discount", "product_url", "product_image_url",
        "product_seller", "product_availability", "product_category",
        "product_subcategory", "product_unit", "product_weight",
        "scraping_time", "timestamp_timezone", "product_brand",
        "product_ram", "product_storage",
    ]

    csv_path = os.path.join(OUTPUT_DIR, "the_beauty_secrets_products.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"CSV: {csv_path} ({len(rows)} rows)")

    json_path = os.path.join(OUTPUT_DIR, "the_beauty_secrets_products.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"JSON: {json_path}")

    # Stats
    with_old = sum(1 for r in rows if r["product_old_price"])
    with_disc = sum(1 for r in rows if r["product_discount"])
    in_stk = sum(1 for r in rows if r["product_availability"] == "in_stock")
    cats = len(set(r["product_category"] for r in rows))
    print(f"\nStats:")
    print(f"  With old price: {with_old}")
    print(f"  With discount: {with_disc}")
    print(f"  In stock: {in_stk}")
    print(f"  Categories: {cats}")
    print("=" * 60)

if __name__ == "__main__":
    main()
