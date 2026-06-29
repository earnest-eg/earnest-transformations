import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests, json, csv, re, time, zipfile, os, concurrent.futures
from datetime import datetime, timezone
from urllib.parse import urljoin

STORES = [
    {"name": "Nasr City EN", "base": "https://cstore-egy.com/nasrcity_store_en"},
    {"name": "Nasr City AR", "base": "https://cstore-egy.com/nasrcity_store_ar"},
    {"name": "Maadi EN", "base": "https://cstore-egy.com/maadi_store_en"},
    {"name": "Maadi AR", "base": "https://cstore-egy.com/maadi_store_ar"},
    {"name": "New Cairo EN", "base": "https://cstore-egy.com/newcairo_store_en"},
    {"name": "New Cairo AR", "base": "https://cstore-egy.com/newcairo_store_ar"},
    {"name": "Masr El Gdeda EN", "base": "https://cstore-egy.com/masr_el_gdeda_store_en"},
    {"name": "Masr El Gdeda AR", "base": "https://cstore-egy.com/masr_el_gdeda_store_ar"},
]

TARGET_COLUMNS = [
    "title","name","product_current_price","product_old_price","product_discount",
    "product_url","product_image_url","product_seller","product_availability",
    "product_category","product_subcategory","product_unit","product_weight",
    "scraping_time","timestamp_timezone","product_brand","product_ram","product_storage"
]

KNOWN_BRANDS = [
    "Samsung","Apple","Nokia","Xiaomi","Realme","Oppo","Vivo","Huawei","LG","Sony",
    "Panasonic","Sharp","Toshiba","Dell","HP","Lenovo","ASUS","Acer","Logitech",
    "JBL","Bose","Sennheiser","Beats","Adidas","Nike","Puma","Pringles","Doritos",
    "Lays","KitKat","Snickers","Mars","Oreo","Nutella","Cadbury","Lindt","Ferrero",
    "Nestle","Coca-Cola","Pepsi","Sprite","Fanta","Schweppes","Mirinda","Sadia",
    "Americana","Sunbulah","Almarai","Nadec","Al Rabee","Al Sabeel","Juhayna",
    "Lactel","Milky Lane","Skippy","Heinz","Maggi","Knorr","Barilla","Abu Auf",
    "Elite","Milka","Kinder","Hershey","Twix","Bounty","Raffaello",
    "Ferrero Rocher","Ghirardelli","Toblerone","Lotus","Biscoff","Chipsy",
    "Cape Cod","Kettle","Mack","Crown","Frito-Lay","Bugles",
    "Cheetos","Ritz","Tuc","LU","McVitie","Galaxy","Godiva",
    "Starbucks","Nescafe","Lipton","Twinings","Ahmad Tea","Dove",
    "Philadelphia","Kraft","Del Monte","Bonduelle","Pedigree","Whiskas",
    "Royal Canin","Palmolive","Head and Shoulders","Pantene","Tide","Persil",
    "Ariel","Comfort","Vanish","Cif","Mr Muscle","Fairy","Ajax","Bref","Glade","Febreze",
]

session = requests.Session()

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', str(text))
    text = re.sub(r'\s+', ' ', text).strip()
    for o,n in [('\u2013','-'),('\u2014','--'),("\u2019","'"),("\u2018","'"),('\u201c','"'),('\u201d','"'),('\u2026','...'),('\u00a0',' ')]:
        text = text.replace(o,n)
    return text.strip()

def parse_price(price_str):
    if not price_str: return ""
    try: return str(int(float(price_str))) if float(price_str)==int(float(price_str)) else f"{float(price_str):.2f}"
    except: return ""

def extract_brand(text):
    tl = text.lower()
    for b in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if b.lower() in tl: return b
    return ""

def extract_specs(text):
    ram=storage=unit=weight=""
    m=re.search(r'(\d+)\s*(?:GB|G)\s*(?:RAM|ram)', text)
    if m: ram=f"{m.group(1)}GB"
    m=re.search(r'(\d+)\s*(?:GB|G|TB)\s*(?:ROM|Storage|SSD|HDD|Internal)', text, re.I)
    if m: storage=f"{m.group(1)}{'TB' if 'TB' in text else 'GB'}"
    m=re.search(r'(\d+[\s]*(?:g|kg|ml|l|L|oz|lb|piece|pcs|pack|pc)[\s\w]*)', text, re.I)
    if m: weight=m.group(1).strip(); unit=weight
    return ram,storage,unit,weight

def get_custom_attr(item, code):
    for attr in item.get("custom_attributes", []):
        if attr["attribute_code"] == code: return attr["value"]
    return ""

def fetch_page(base_url, page, page_size=100):
    url = f"{base_url}/rest/V1/products?searchCriteria[pageSize]={page_size}&searchCriteria[currentPage]={page}"
    for attempt in range(3):
        try:
            r = session.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < 2:
                time.sleep(3*(attempt+1))
            else:
                raise e

def fetch_store_products(base_url, store_name):
    all_items = []
    try:
        first = fetch_page(base_url, 1)
        total = first.get("total_count", 0)
        total_pages = (total + 99) // 100
        print(f"  {store_name}: {total} products, {total_pages} pages", flush=True)
        all_items.extend(first.get("items", []))

        pages = list(range(2, total_pages+1))
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(fetch_page, base_url, p): p for p in pages}
            for fut in concurrent.futures.as_completed(futs):
                p = futs[fut]
                try:
                    data = fut.result()
                    items = data.get("items",[])
                    all_items.extend(items)
                    print(f"    {store_name} p{p}: +{len(items)}={len(all_items)}/{total}", flush=True)
                except Exception as e:
                    print(f"    {store_name} p{p}: FAILED {e}", flush=True)
                time.sleep(0.1)
    except Exception as e:
        print(f"  {store_name}: FAILED {e}", flush=True)
        return [], 0
    return all_items, total

def parse_product(item, base_url):
    pid = item.get("id"); sku = item.get("sku","")
    name = clean_text(item.get("name",""))
    price = item.get("price",0)
    desc = clean_text(get_custom_attr(item,"description"))
    sdesc = clean_text(get_custom_attr(item,"short_description"))
    image = get_custom_attr(item,"image")
    url_key = get_custom_attr(item,"url_key")
    brand = clean_text(get_custom_attr(item,"manufacturer") or get_custom_attr(item,"brand"))
    sp = get_custom_attr(item,"special_price")

    product_url = f"{base_url}/{url_key}.html" if url_key else f"{base_url}/catalog/product/view/id/{pid}/"
    product_image_url = ""
    if image and image!="no_selection":
        product_image_url = urljoin(f"{base_url}/",f"media/catalog/product/cache/abb26ec7d3aecacf123a2c86145b5ff8{image}")

    cur_price = parse_price(price)
    old_price = parse_price(sp) if sp and float(sp)>float(price) else ""
    disc = ""
    if old_price and cur_price:
        ov, cv = float(old_price), float(cur_price)
        if ov>cv: disc = f"{((ov-cv)/ov)*100:.3f}%"

    product_brand = brand if brand else extract_brand(f"{name}")
    ram,storage,unit,weight = extract_specs(f"{name} {desc} {sdesc} {sku}")
    subcat = ""
    if url_key:
        p = url_key.split("/")
        if len(p)>1: subcat = p[0].replace("-"," ").title()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return {"title":name,"name":name,"product_current_price":cur_price,"product_old_price":old_price,
            "product_discount":disc,"product_url":product_url,"product_image_url":product_image_url,
            "product_seller":"C Store","product_availability":"in_stock","product_category":"",
            "product_subcategory":subcat,"product_unit":unit,"product_weight":weight,
            "scraping_time":now,"timestamp_timezone":"Africa/Cairo","product_brand":product_brand,
            "product_ram":ram,"product_storage":storage}

def deduplicate(products, key="product_url"):
    seen=set(); result=[]
    for p in products:
        k=p.get(key,"")
        if k not in seen: seen.add(k); result.append(p)
    return result

def main():
    print("="*70, flush=True)
    print("CStore Multi-Store Scraper v4", flush=True)
    print("="*70, flush=True)

    all_rows = []
    store_stats = {}

    for store in STORES:
        name, base = store["name"], store["base"]
        print(f"\n{'='*60}", flush=True)
        print(f"  Store: {name}", flush=True)
        print(f"  URL: {base}", flush=True)
        print(f"{'='*60}", flush=True)

        t0 = time.time()
        items, total = fetch_store_products(base, name)
        fetch_time = time.time()-t0
        print(f"  Fetched {len(items)}/{total} in {fetch_time:.0f}s", flush=True)
        if not items:
            store_stats[name] = {"total":total,"fetched":0,"parsed":0}
            continue

        t0 = time.time()
        parsed = [parse_product(i, base) for i in items]
        parse_time = time.time()-t0
        store_stats[name] = {"total":total,"fetched":len(items),"parsed":len(parsed)}
        print(f"  Parsed {len(parsed)} in {parse_time:.0f}s", flush=True)
        all_rows.extend(parsed)

    print(f"\n{'='*70}", flush=True)
    print(f"TOTAL across stores: {len(all_rows)}", flush=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"cstore_all_stores_{ts}.csv"
    with open(csv_path,"w",newline="",encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=TARGET_COLUMNS); w.writeheader(); w.writerows(all_rows)
    json_path = f"cstore_all_stores_{ts}.json"
    with open(json_path,"w",encoding="utf-8") as f:
        json.dump(all_rows,f,ensure_ascii=False,indent=2)
    zip_path = f"cstore_all_stores_{ts}.zip"
    with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED) as z:
        z.write(csv_path,os.path.basename(csv_path)); z.write(json_path,os.path.basename(json_path))

    prices = [float(r["product_current_price"]) for r in all_rows if r["product_current_price"]]
    print(f"\n{'='*70}", flush=True)
    print(f"FINAL SUMMARY", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"  Total products: {len(all_rows)}", flush=True)
    if prices:
        print(f"  Price range: {min(prices):.2f} - {max(prices):.2f}", flush=True)
        print(f"  Avg price: {sum(prices)/len(prices):.2f}", flush=True)
    print(f"\n  Per-store:", flush=True)
    for n,s in store_stats.items():
        print(f"    {n}: fetched {s['fetched']}/{s['total']}, parsed {s['parsed']}", flush=True)
    print(f"\n  Files:", flush=True)
    print(f"    CSV: {csv_path}", flush=True)
    print(f"    JSON: {json_path}", flush=True)
    print(f"    ZIP: {zip_path}", flush=True)

if __name__=="__main__":
    main()
