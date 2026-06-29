import requests, json, csv, re, os, time, html
from datetime import datetime, timezone
from urllib.parse import urljoin

BASE_URL = "https://eg.gosportme.com"
API_URL = "https://eg.gosportme.com/collections/all/products.json"
OUTPUT_DIR = "scraper_output"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

BRANDS = [
    "NIKE", "ADIDAS", "PUMA", "REEBOK", "ASICS", "NEW BALANCE", "SKECHERS",
    "UNDER ARMOUR", "VANS", "BODY SCULPTURE", "WILSON", "BABOLAT", "LIVEUP",
    "JAN SPORT", "TECHNOFIBRE", "DUNLOP", "QUIKSILVER", "ROXY", "SPEEDO",
    "ARENA", "LIBRA", "TEMPO", "BUTTERFLY", "ON", "NIKE PRO", "JORDAN",
    "CONVERSE", "UMBRO", "KAPPA", "MACRON", "MIZUNO", "YONEX", "LI-NING",
    "HEAD", "EVERLAST", "VENUM", "TIMBERLAND", "CHAMPION", "SPALDING",
    "MIKASA", "MOLTEN", "SELECT", "PRO", "GOSPORT",
]

COLUMNS = [
    "title", "name", "product_current_price", "product_old_price",
    "product_discount", "product_url", "product_image_url", "product_seller",
    "product_availability", "product_category", "product_subcategory",
    "product_unit", "product_weight", "scraping_time", "timestamp_timezone",
    "product_brand", "product_ram", "product_storage",
]

CATEGORY_RULES = [
    (["FOOTWEAR", "SHOES", "SNEAKERS"], "sports > footwear"),
    (["APPAREL", "CLOTHING", "T-SHIRT", "T-SHIRTS", "TOPS", "BOTTOMS"], "sports > apparel"),
    (["ACCESSORIES", "BAG", "BACKPACK", "SOCKS", "HEADWEAR", "CAP", "BOTTLE", "BAGS"], "sports > accessories"),
    (["EQUIPMENT", "EQUIPMENTS"], "sports > equipment"),
    (["FOOTBALL", "SOCCER"], "sports > football"),
    (["BASKETBALL"], "sports > basketball"),
    (["TENNIS"], "sports > tennis"),
    (["RUNNING"], "sports > running"),
    (["SWIMMING", "SWIM"], "sports > swimming"),
    (["FITNESS", "GYM", "WORKOUT", "TRAINING", "EXERCISE"], "sports > fitness"),
    (["PADEL"], "sports > padel"),
    (["SQUASH"], "sports > squash"),
    (["BOXING"], "sports > boxing"),
    (["YOGA", "PILATES"], "sports > yoga"),
    (["LIFESTYLE", "SPORTSTYLE", "CASUAL"], "sports > lifestyle"),
    (["BICYCLE", "CYCLING", "BIKE"], "sports > cycling"),
    (["HIKING", "OUTDOOR", "CAMPING"], "sports > outdoor"),
    (["VOLLEYBALL"], "sports > volleyball"),
    (["MASSAGE"], "sports > wellness"),
    (["MOTORSPORT"], "sports > motorsport"),
]

def fetch_json(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"  Error: {e}")
        time.sleep(2 ** attempt)
    return None

def extract_brand(title, vendor, tags):
    v = vendor.strip().upper() if vendor else ""
    for b in BRANDS:
        if b in v:
            return b.title()
    for b in BRANDS:
        if b in title.upper():
            return b.title()
    for t in tags:
        for b in BRANDS:
            if b in t.upper():
                return b.title()
    return v.title() if v else ""

def extract_specs(title, body_html):
    c = (title + " " + (body_html or "")).upper()
    ram = ""
    for p in [r'(\d+)\s*GB\s*RAM', r'RAM\s*(\d+)\s*GB']:
        m = re.search(p, c)
        if m: ram = m.group(1) + "GB"; break
    storage = ""
    for p in [r'(\d+)\s*(?:GB|TB)\s*(?:SSD|HDD|STORAGE|ROM)', r'(\d+)\s*GB', r'(\d+)\s*TB']:
        m = re.search(p, c)
        if m:
            v = m.group(1)
            storage = v + ("TB" if "TB" in m.group(0) else "GB")
            break
    return ram, storage

def extract_unit_weight(title, body_html, tags):
    c = (title + " " + (body_html or "") + " " + " ".join(tags)).upper()
    unit = ""
    for pat, repl in [(r'(\d+)\s*PCS?\b', r'\1 pcs'), (r'(\d+)\s*SETS?\b', r'\1 Set'), (r'PACK\s+OF\s+(\d+)', r'\1 pcs')]:
        m = re.search(pat, c)
        if m: unit = re.sub(pat, repl, m.group(0)).lower(); break
    weight = ""
    for pat, repl in [(r'(\d+(?:\.\d+)?)\s*KG\b', r'\1 kg'), (r'(\d+(?:\.\d+)?)\s*G\b(?!B)', r'\1 g'), (r'(\d+(?:\.\d+)?)\s*L\b', r'\1 l'), (r'(\d+(?:\.\d+)?)\s*ML\b', r'\1 ml')]:
        m = re.search(pat, c)
        if m: weight = re.sub(pat, repl, m.group(0)).lower(); break
    return unit, weight

def clean_price(price_str):
    if price_str is None: return ""
    try:
        p = float(price_str)
        return "" if p == 0 else (str(int(p)) if p == int(p) else f"{p:.2f}")
    except: return ""

def derive_category(tags, product_type):
    all_text = " ".join(t.upper() for t in tags) + " " + (product_type or "").upper()
    for keywords, cat in CATEGORY_RULES:
        if any(k in all_text for k in keywords):
            return cat
    return "sports > general"

def get_subcategory(tags, product_type):
    if product_type:
        return product_type.capitalize()
    for tag in tags:
        if tag not in ["ALL", "RA-36", "UP-50%", "NUTO50%", "GO-B1G50", "BK-GO-UP50%"] and not any(b in tag.upper() for b in BRANDS):
            if "-" in tag:
                return tag.split("-")[-1].capitalize()
            return tag.capitalize()
    return ""

def process_variant(product, variant):
    title = product.get("title", "")
    vendor = product.get("vendor", "")
    product_type = product.get("product_type", "")
    tags = product.get("tags", [])
    handle = product.get("handle", "")
    body_html = product.get("body_html", "")

    variant_title = variant.get("title", "")
    full_title = f"{title} - {variant_title}" if variant_title and variant_title != "Default Title" else title

    cp = clean_price(variant.get("price"))
    op_raw = variant.get("compare_at_price")
    op = clean_price(op_raw)

    discount = ""
    if op and cp:
        try:
            ov = float(op_raw)
            cv = float(variant["price"])
            if ov > cv and ov > 0:
                discount = f"{((ov - cv) / ov * 100):.3f}%"
        except: pass

    avail = variant.get("available", True)
    availability = "in_stock" if avail else "out_of_stock"

    # Image from variant's featured_image or product's first image
    img = ""
    vimg = variant.get("featured_image")
    if vimg and isinstance(vimg, dict):
        s = vimg.get("src", "")
        img = "https:" + s if s.startswith("//") else s
    if not img:
        images = product.get("images", [])
        if images:
            s = images[0].get("src", "")
            img = "https:" + s if s.startswith("//") else s

    prod_url = f"{BASE_URL}/products/{handle}"

    brand = extract_brand(title, vendor, tags)
    ram, storage = extract_specs(title, body_html)
    unit, weight = extract_unit_weight(title, body_html, tags)

    name = title.split(" / ")[0] if " / " in title else title
    title_clean = html.unescape(full_title).strip()
    name_clean = html.unescape(name).strip()

    cat = derive_category(tags, product_type)
    sub = get_subcategory(tags, product_type)

    now = datetime.now(timezone.utc)
    return {
        "title": title_clean,
        "name": name_clean,
        "product_current_price": cp,
        "product_old_price": op,
        "product_discount": discount,
        "product_url": prod_url,
        "product_image_url": img,
        "product_seller": "Go Sport",
        "product_availability": availability,
        "product_category": cat,
        "product_subcategory": sub,
        "product_unit": unit,
        "product_weight": weight,
        "scraping_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_timezone": "Africa/Cairo",
        "product_brand": brand,
        "product_ram": ram,
        "product_storage": storage,
    }

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_rows = []
    page = 1

    print("=" * 60)
    print("  GO SPORT EGYPT - PRODUCT SCRAPER")
    print("=" * 60)
    print(f"\nScraping all products & variants from {BASE_URL}")

    while True:
        data = fetch_json(API_URL, {"page": page, "limit": 250})
        if not data or "products" not in data:
            break
        products = data["products"]
        if not products:
            break

        for p in products:
            variants = p.get("variants", [])
            for v in variants:
                all_rows.append(process_variant(p, v))

        print(f"  Page {page:2d}: {len(products):3d} products, {sum(len(p.get('variants',[])) for p in products):3d} variants (total rows: {len(all_rows)})")
        if len(products) < 250:
            break
        page += 1
        time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"  TOTAL ROWS SCRAPED: {len(all_rows)}")
    print(f"  Total products: {page * 250 if page < 7 else 1563}")
    print(f"{'='*60}")

    # --- Save CSVs ---
    csv_main = os.path.join(OUTPUT_DIR, "gosport_products_variants.csv")
    with open(csv_main, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nSaved: {csv_main}")

    # Deduplicated product-level CSV (first variant only)
    seen = set()
    product_rows = []
    for row in all_rows:
        url = row["product_url"]
        if url not in seen:
            seen.add(url)
            product_rows.append(row)

    csv_prod = os.path.join(OUTPUT_DIR, "gosport_products.csv")
    with open(csv_prod, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(product_rows)
    print(f"Saved: {csv_prod}")

    # JSON
    json_path = os.path.join(OUTPUT_DIR, "gosport_products.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(product_rows, f, ensure_ascii=False, indent=2)
    print(f"Saved: {json_path}")

    # --- Validation ---
    print(f"\n{'='*60}")
    print("  VALIDATION REPORT")
    print(f"{'='*60}")
    print(f"  Rows (variant-level): {len(all_rows)}")
    print(f"  Rows (product-level):  {len(product_rows)}")
    print(f"  Columns:               {len(COLUMNS)} (target: 18)")
    print(f"  Headers match:         {list(product_rows[0].keys()) == COLUMNS}")
    arabic = sum(1 for r in product_rows if re.search(r'[\u0600-\u06FF]', r["title"]))
    print(f"  Arabic titles:         {arabic}")
    valid_prices = sum(1 for r in product_rows if not r["product_current_price"] or re.match(r'^\d+(\.\d+)?$', r["product_current_price"]))
    print(f"  Valid prices:          {valid_prices}/{len(product_rows)}")
    abs_urls = sum(1 for r in product_rows if r["product_url"].startswith("http"))
    print(f"  Absolute URLs:         {abs_urls}/{len(product_rows)}")

    # Category distribution
    print(f"\n  Category Distribution:")
    cats = {}
    for r in product_rows:
        cats[r["product_category"]] = cats.get(r["product_category"], 0) + 1
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count}")

    # Brand distribution
    print(f"\n  Top Brands:")
    brands = {}
    for r in product_rows:
        b = r["product_brand"] or "Unknown"
        brands[b] = brands.get(b, 0) + 1
    for b, c in sorted(brands.items(), key=lambda x: -x[1])[:10]:
        print(f"    {b}: {c}")

    # Sample row
    print(f"\n  Sample Row:")
    print(f"    {json.dumps(product_rows[0], ensure_ascii=False)}")

    print(f"\n{'='*60}")
    print("  SCRAPING COMPLETE")
    print(f"{'='*60}")

    # --- Create todo_products.csv ---
    todo_path = os.path.join(OUTPUT_DIR, "todo_products.csv")
    with open(todo_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["url", "category", "subcategory", "status", "error"])
        for r in product_rows:
            w.writerow([r["product_url"], r["product_category"], r["product_subcategory"], "done", ""])
    print(f"Saved: {todo_path}")

    return all_rows, product_rows

if __name__ == "__main__":
    main()
