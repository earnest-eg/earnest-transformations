import requests
from bs4 import BeautifulSoup
import csv
import json
import os
import time
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading

# Configuration
INPUT_FILE = "elghazawy_scraper/todo_products.csv"
OUTPUT_FILE = "elghazawy_scraper/data/elghazawy_products.csv"
ERROR_FILE = "elghazawy_scraper/error_products.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
MAX_WORKERS = 25
TIMEZONE = "Africa/Cairo"

# Lock for writing to CSV
csv_lock = threading.Lock()

COLUMNS = [
    "title", "name", "product_current_price", "product_old_price", "product_discount",
    "product_url", "product_image_url", "product_seller", "product_availability",
    "product_category", "product_subcategory", "product_unit", "product_weight",
    "scraping_time", "timestamp_timezone", "product_brand", "product_ram", "product_storage"
]

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"').replace('\u200e', '').replace('\u200f', '')
    return " ".join(text.split())

def extract_numeric(text):
    if not text:
        return None
    text = text.replace(',', '').replace('EGP', '').replace('LE', '').strip()
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match:
        try:
            return float(match.group(1))
        except:
            return None
    return None

def extract_brand(title, soup):
    brand = ""
    brand_tag = soup.select_one('.brnd-name') or soup.select_one('.product-brand')
    if brand_tag:
        brand = clean_text(brand_tag.get_text())
    if not brand and title:
        brand = title.split()[0]
    return brand

def extract_specs(soup):
    specs = {}
    rows = soup.select('.pro-frame tr') or soup.select('table tr')
    for row in rows:
        cols = row.find_all(['td', 'th'])
        if len(cols) >= 2:
            key = clean_text(cols[0].get_text()).lower().strip(':')
            val = clean_text(cols[1].get_text())
            specs[key] = val
    return specs

def extract_ram_storage(title, specs):
    ram = ""
    storage = ""
    text_to_search = (title + " " + " ".join(specs.values())).upper()
    ram_match = re.search(r'(\d+)\s*(?:GB|G)\s*RAM', text_to_search)
    if ram_match:
        ram = ram_match.group(1) + "GB"
    else:
        for k, v in specs.items():
            if 'ram' in k:
                ram = v.upper().replace(' ', '')
                if not ram.endswith('GB') and ram.isdigit(): ram += 'GB'
                break
    storage_match = re.search(r'(\d+)\s*(?:GB|TB|G)\s*(?:INTERNAL|ROM|STORAGE|SSD|HDD)', text_to_search)
    if not storage_match:
        storage_match = re.search(r'(\d+)\s*(?:GB|TB|G)', text_to_search)
    if storage_match:
        val = storage_match.group(1)
        unit = 'GB'
        if 'TB' in storage_match.group(0): unit = 'TB'
        storage = val + unit
    else:
        for k, v in specs.items():
            if 'storage' in k or 'memory' in k or 'internal' in k:
                storage = v.upper().replace(' ', '')
                break
    return ram, storage

def scrape_product(url, category_hint):
    for attempt in range(2):
        try:
            res = requests.get(url, headers=HEADERS, timeout=30)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'html.parser')
            
            title_tag = soup.find('h1') or soup.select_one('.product-title')
            title = clean_text(title_tag.get_text()) if title_tag else ""
            if not title: continue
                
            name = title.split(',')[0].split('-')[0].strip()
            
            price_tag = soup.select_one('.pro-praice') or soup.select_one('.h2-price') or \
                        soup.select_one('.product-price') or soup.select_one('.current-price') or \
                        soup.select_one('.price')
            
            current_price = extract_numeric(price_tag.get_text()) if price_tag else None
            
            # Search broader if price tag is missing
            if current_price is None:
                price_section = soup.select_one('.content-main') or soup.select_one('.pro-info-slider')
                if price_section:
                    matches = re.findall(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)', price_section.get_text())
                    if matches: current_price = extract_numeric(matches[0])

            old_price_tag = soup.select_one('.old-price') or soup.select_one('del') or \
                            soup.find(style=lambda x: x and 'line-through' in x)
            old_price = extract_numeric(old_price_tag.get_text()) if old_price_tag else None
            
            discount = ""
            if old_price and current_price and old_price > current_price:
                discount = f"{((old_price - current_price) / old_price) * 100:.3f}%"
                
            image_tag = soup.select_one('.product-image-main img') or \
                        soup.select_one('.main-image-container img') or \
                        soup.select_one('.pro-info-slider img')
            image_url = ""
            if image_tag:
                image_url = image_tag.get('src') or image_tag.get('data-src') or ""
                if image_url.startswith('//'): image_url = "https:" + image_url
                elif image_url.startswith('/'): image_url = "https://elghazawy.com" + image_url
            
            availability = "in_stock"
            avail_text = soup.get_text().lower()
            if any(x in avail_text for x in ["out of stock", "not available", "sold out"]):
                availability = "out_of_stock"
                
            breadcrumbs = [clean_text(a.get_text()) for a in soup.select('.breadcrumb-me a')]
            if len(breadcrumbs) >= 2:
                product_category = " > ".join(breadcrumbs[1:3]).lower()
                product_subcategory = breadcrumbs[-1] if len(breadcrumbs) > 2 else ""
            else:
                product_category = category_hint.lower()
                product_subcategory = ""
                
            specs = extract_specs(soup)
            brand = extract_brand(title, soup)
            ram, storage = extract_ram_storage(title, specs)
            unit = specs.get('unit', '')
            weight = ""
            for p in [r'(\d+(?:\.\d+)?\s*(?:KG|L|ML))', r'(\d+(?:\.\d+)?\s*(?:G))\b']:
                m = re.search(p, (title + " " + " ".join(specs.values())).upper())
                if m and not re.search(m.group(1) + r'\s*(?:RAM|INTERNAL|ROM|STORAGE)', (title + " " + " ".join(specs.values())).upper()):
                    weight = m.group(1)
                    break
            
            return {
                "title": title, "name": name, "product_current_price": current_price,
                "product_old_price": old_price, "product_discount": discount,
                "product_url": url, "product_image_url": image_url,
                "product_seller": "Elghazawy Shop", "product_availability": availability,
                "product_category": product_category, "product_subcategory": product_subcategory,
                "product_unit": unit, "product_weight": weight,
                "scraping_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp_timezone": TIMEZONE, "product_brand": brand,
                "product_ram": ram, "product_storage": storage
            }
        except Exception as e:
            time.sleep(1)
            continue
    return None

def main():
    if not os.path.exists(INPUT_FILE): return
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writeheader()
    todo_list = []
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader: todo_list.append(row)
    print(f"Total: {len(todo_list)}")
    counter = 0
    total = len(todo_list)
    def worker(item):
        nonlocal counter
        res_data = scrape_product(item['url'], item['category'])
        if res_data:
            with csv_lock:
                with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8') as f:
                    csv.DictWriter(f, fieldnames=COLUMNS).writerow(res_data)
        counter += 1
        if counter % 50 == 0: print(f"Progress: {counter}/{total} ({(counter/total)*100:.2f}%)")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(worker, todo_list)

if __name__ == "__main__":
    main()
