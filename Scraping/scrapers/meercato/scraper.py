import sys, io, csv, os, re, json, asyncio, aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import urljoin

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_URL = "https://meercato.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = aiohttp.ClientTimeout(total=30)
SEMAPHORE_LIMIT = 10

TARGET_COLUMNS = [
    "title", "name", "product_current_price", "product_old_price",
    "product_discount", "product_url", "product_image_url", "product_seller",
    "product_availability", "product_category", "product_subcategory",
    "product_unit", "product_weight", "scraping_time", "timestamp_timezone",
    "product_brand", "product_ram", "product_storage"
]

CATEGORY_MAP = {
    "table-ware": "home > tableware",
    "tableware": "home > tableware",
    "dinning-sets": "home > tableware > dinner-sets",
    "dinner-sets": "home > tableware > dinner-sets",
    "plates": "home > tableware > plates",
    "fine-dinning-sets": "home > tableware > fine-dinner-sets",
    "serving": "home > tableware > serving",
    "tableware-sets": "home > tableware > serving",
    "dessert-serving": "home > tableware > dessert-serving",
    "cutlery-sets": "home > tableware > cutlery",
    "cookware": "home > cookware",
    "cooking-pans": "home > cookware > cooking-pans",
    "cookware-single-pots": "home > cookware > single-pots",
    "cookware-sets": "home > cookware > cookware-sets",
    "bakeware": "home > bakeware",
    "baking-tools": "home > bakeware > baking-tools",
    "roasters": "home > bakeware > roasters",
    "baking-pans": "home > bakeware > baking-pans",
    "kitchen-tools": "home > kitchen-tools",
    "food-preparation": "home > kitchen-tools > food-preparation",
    "gadgets": "home > kitchen-tools > gadgets",
    "cutting-tools": "home > kitchen-tools > cutting-tools",
    "utensils": "home > kitchen-tools > utensils",
    "kitchen-organizer": "home > kitchen-tools > kitchen-organizers",
    "drinkware": "home > drinkware",
    "goblet": "home > drinkware > goblets",
    "jugs": "home > drinkware > jugs",
    "sets": "home > drinkware > sets",
    "tumbler": "home > drinkware > tumblers",
    "double-wall-collection": "home > drinkware > double-wall",
    "water-bottles": "home > drinkware > water-bottles",
    "tea-coffee-lovers": "home > tea-coffee",
    "tea-coffee": "home > tea-coffee",
    "tea-coffee-sets": "home > tea-coffee > sets",
    "tea-coffee-serving": "home > tea-coffee > serving",
    "trays": "home > tea-coffee > trays",
    "mugs-thermos": "home > tea-coffee > mugs-thermos",
    "tea-coffee-preparation": "home > tea-coffee > preparation",
    "kitchen-storage": "home > kitchen-storage",
    "storage": "home > kitchen-storage > storage",
    "food-container": "home > kitchen-storage > food-containers",
    "beverage-containers": "home > kitchen-storage > beverage-containers",
    "wooden": "home > wooden-collection",
    "wooden/serving": "home > wooden-collection > serving",
    "wooden/kitchen-storage": "home > wooden-collection > kitchen-storage",
    "wooden/tea-coffee-lovers": "home > wooden-collection > tea-coffee",
    "wooden/cutting-tools": "home > wooden-collection > cutting-tools",
    "homeware": "home > homeware",
    "cleaning": "home > homeware > cleaning",
    "storage-organizing": "home > homeware > storage-organizing",
    "laundry-basket": "home > homeware > laundry",
    "bathroom-accessories": "home > homeware > bathroom",
}

def clean_price(text):
    if not text:
        return ""
    text = re.sub(r"[^\d.,]", "", text)
    text = text.replace(",", "")
    try:
        return str(int(float(text)))
    except:
        return text.strip()

def extract_discount(old_price, current_price):
    try:
        old = float(old_price)
        cur = float(current_price)
        if old > 0 and old > cur:
            disc = ((old - cur) / old) * 100
            return f"{disc:.3f}%"
    except:
        pass
    return ""

def extract_specs(soup):
    specs = {}
    for row in soup.select(".spec-row"):
        label = row.select_one(".spec-label")
        value = row.select_one(".spec-value")
        if label and value:
            key = label.get_text(strip=True).lower().strip().rstrip(":")
            val = value.get_text(strip=True).strip()
            specs[key] = val
    return specs

def extract_unit_weight(title, specs):
    unit = ""
    weight = ""
    
    weight_patterns = [
        (r"(\d+\.?\d*)\s*(?:ml|milliliter|millilitre)", r"\1 ml"),
        (r"(\d+\.?\d*)\s*(?:l|litre|liter|lt)", r"\1 l"),
        (r"(\d+\.?\d*)\s*(?:g|gram|gr)", r"\1 g"),
        (r"(\d+\.?\d*)\s*(?:kg|kilo|kilogram)", r"\1 kg"),
        (r"(\d+)\s*(?:pcs|pieces|piece|pc)", r"\1 pcs"),
    ]
    
    for pat, repl in weight_patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            weight = re.sub(pat, repl, m.group(0), flags=re.IGNORECASE)
            unit = weight
            break
    
    for key, val in specs.items():
        keyl = key.lower()
        if "gross weight" in keyl:
            w = val.strip()
            if re.search(r"\d", w):
                unit = " kg" if not any(u in w.lower() for u in ["kg", "g ", "kgs", "pounds", "lb"]) else ""
                weight = w + unit if unit else w
                break
        elif "weight" in keyl and "gross" not in keyl:
            w = val.strip()
            if re.search(r"\d", w) and not weight:
                unit = " kg" if not any(u in w.lower() for u in ["kg", "g ", "kgs", "pounds", "lb", "ml", "l "]) else ""
                weight = w + unit if unit else w
    
    for key, val in specs.items():
        if "components" in key or "number of" in key:
            m = re.search(r"(\d+)", val)
            if m and not unit:
                unit = f"{m.group(1)} pcs"
                break
        if key == "number of pieces":
            m = re.search(r"(\d+)", val)
            if m and not unit:
                unit = f"{m.group(1)} pcs"
    
    return unit, weight

def extract_brand(soup, title, specs):
    for key, val in specs.items():
        if key == "brand":
            b = val.strip()
            if b.lower() not in ["other", "others", "none", "n/a", "", "-"]:
                return b
            break
    m = re.search(r"^(Neoflam|Tramontina|Luminarc|Pyrex|RCR|Korkmaz|Vivaldi|Ecoten|Aboud|Lahoya|Cookin|Jewel|Bohemia|Nehir|Libbey|Rosa|Tulu|Alsherif|Porser|Karolina|Kutahya|Qualitier|Axa|Zinnia|Termisil|Oxford|Homi\s*Plus|Bass|Neo[-\s]?Flam|Maya|Carolina|Cooker|Golden[\s-]?Star|Sandy|Cloudy[\s-]?Ivory|Modern[\s-]?Flory|Royal|M[\s-]?Design|Zig[\s-]?Zag|Willini|RCR[\s-]?Crystal|Alex)\b", title, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""

def extract_availability(soup):
    stock_el = soup.select_one(".stock-value")
    if stock_el:
        txt = stock_el.get_text(strip=True).lower()
        if "out" in txt:
            return "out_of_stock"
        if "in" in txt:
            return "in_stock"
    # Fallback
    text = soup.get_text()
    if re.search(r"out\s*of\s*stock", text, re.IGNORECASE):
        return "out_of_stock"
    if re.search(r"in\s*stock|add\s*to\s*cart", text, re.IGNORECASE):
        return "in_stock"
    return ""

def extract_image_url(soup):
    # Main product image in gallery section
    for img in soup.select("[class*=gallery] img[src*='catalog/product'], .product-image img[src*='catalog/product'], img[src*='catalog/product'][width]"):
        src = img.get("src", "")
        if src and "media/catalog/product" in src:
            src = re.sub(r"\?.*", "", src)
            if not src.startswith("http"):
                src = urljoin(BASE_URL, src)
            return src
    
    # Fallback: any product image with the largest size
    for img in soup.select("img[src*='catalog/product']"):
        src = img.get("src", "")
        if "media/catalog/product" in src:
            src = re.sub(r"\?.*", "", src)
            if not src.startswith("http"):
                src = urljoin(BASE_URL, src)
            return src
    
    return ""

def extract_breadcrumbs(soup):
    crumbs = []
    for a in soup.select("[class*=breadcrumb] a, [class*=breadcrumbs] a"):
        txt = a.get_text(strip=True)
        if txt and txt.lower() not in ["home", "skip to content", "", "click here"]:
            crumbs.append(txt)
    return crumbs

def map_category(url, breadcrumbs):
    url_path = url.replace(BASE_URL, "").strip("/")
    
    skip_words = ["offers", "offer", "sale", "less than", "end of year", "mother", "eid", "summer", "ramadan", "school", "el sahel", "save"]
    
    clean_crumbs = []
    for b in breadcrumbs:
        b_lower = b.lower()
        if b_lower == "home":
            continue
        skip = False
        for sw in skip_words:
            if sw in b_lower:
                skip = True
                break
        if not skip:
            clean_crumbs.append(b)
    
    def lookup(key):
        for k, v in sorted(CATEGORY_MAP.items(), key=lambda x: -len(x[0])):
            if k in key:
                return v
        return None
    
    if clean_crumbs:
        bread_path = " > ".join(clean_crumbs)
        bread_path_key = bread_path.lower().replace(" ", "-")
        val = lookup(bread_path_key)
        if val:
            return val, ""
    
    val = lookup(url_path)
    if val:
        return val, ""
    
    if clean_crumbs:
        return "home > " + clean_crumbs[0].lower().replace(" ", "-"), " > ".join(clean_crumbs[1:])
    
    return "home > kitchenware", ""

async def scrape_product(session, url, semaphore):
    async with semaphore:
        try:
            async with session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True) as resp:
                if resp.status != 200:
                    return {"error": f"HTTP {resp.status}", "url": url}
                html = await resp.text()
        except Exception as e:
            return {"error": str(e), "url": url}
    
    try:
        soup = BeautifulSoup(html, "lxml")
        
        # Title
        title_el = soup.select_one("h1, [class*=product-name], [class*=page-title], h1 span")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            title_tag = soup.select_one("title")
            if title_tag:
                title = title_tag.get_text(strip=True).split("|")[0].strip()
        
        # Name: shorter version without color/variant noise
        name = title
        # Remove color info at end if present
        name = re.sub(r"\s*[-–]\s*(?:Green|Blue|Red|Black|White|Grey|Gray|Pink|Yellow|Brown|Beige|Silver|Gold|Transparent|Cream|Sand|Peach|Navy|Mint|Orange|Purple|Multi[-\s]?[Cc]olor|Assorted[-\s]?[Cc]olor|Rose|Marble|Woody|Stone|Honey|Ivory|Teal|Lavender|Mauve|Olive)\s*$", "", name).strip()
        if not name:
            name = title
        
        # Prices - use the price-container which contains both old and final
        old_price_el = soup.select_one(".price-container .old-price .price, .price-container .old-price .price-wrapper .price")
        current_price_el = soup.select_one(".price-container .final-price[itemprop=offers] .price, .price-container .final-price .price-wrapper .price")
        
        current_price = ""
        old_price = ""
        
        if current_price_el:
            current_price = clean_price(current_price_el.get_text(strip=True))
        if not current_price:
            # Try any price within product-info section
            for p in soup.select("[class*=product-info] .price, [class*=product-detail] .price"):
                txt = clean_price(p.get_text(strip=True))
                if txt:
                    current_price = txt
                    break
        
        if old_price_el:
            old_price = clean_price(old_price_el.get_text(strip=True))
        
        discount = extract_discount(old_price, current_price)
        
        # Image
        image_url = extract_image_url(soup)
        
        # Availability
        availability = extract_availability(soup)
        
        # Specs
        specs = extract_specs(soup)
        
        # Brand
        brand = extract_brand(soup, title, specs)
        
        # Breadcrumbs
        breadcrumbs = extract_breadcrumbs(soup)
        
        # Category
        product_category, product_subcategory = map_category(url, breadcrumbs)
        
        # Unit and Weight
        unit, weight = extract_unit_weight(title, specs)
        
        scraping_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        
        product = {
            "title": title,
            "name": name,
            "product_current_price": current_price,
            "product_old_price": old_price,
            "product_discount": discount,
            "product_url": url,
            "product_image_url": image_url,
            "product_seller": "Meercato",
            "product_availability": availability,
            "product_category": product_category,
            "product_subcategory": product_subcategory,
            "product_unit": unit,
            "product_weight": weight,
            "scraping_time": scraping_time,
            "timestamp_timezone": "Africa/Cairo",
            "product_brand": brand,
            "product_ram": "",
            "product_storage": "",
        }
        return product
    except Exception as e:
        return {"error": str(e), "url": url}

async def main():
    input_csv = "todo_products.csv"
    output_csv = "meercato_products.csv"
    
    urls = []
    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url_key = [k for k in row.keys() if "url" in k.lower()][0]
            url = row.get(url_key, "").strip()
            if url:
                urls.append(url)
    
    print(f"Total product URLs to scrape: {len(urls)}")
    
    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    connector = aiohttp.TCPConnector(limit=20, force_close=True)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [scrape_product(session, url, semaphore) for url in urls]
        results = []
        done = 0
        errors = 0
        
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if "error" in result:
                errors += 1
                if errors <= 10:
                    print(f"Error ({errors}): {result['url']} - {result['error']}")
            else:
                results.append(result)
            done += 1
            if done % 50 == 0:
                print(f"Progress: {done}/{len(urls)} (errors: {errors})")
        
        print(f"\nScraping complete. Success: {len(results)}, Errors: {errors}")
        
        if results:
            with open(output_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=TARGET_COLUMNS)
                writer.writeheader()
                writer.writerows(results)
            print(f"CSV written to {output_csv} with {len(results)} rows")
        
        json_path = output_csv.replace(".csv", ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"JSON written to {json_path}")
        
        return results

if __name__ == "__main__":
    results = asyncio.run(main())
