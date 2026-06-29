import requests
import json
import csv
import math
import re
from datetime import datetime
import pytz

def get_product_data():
    url = 'https://be.fresh.com.eg/graphql'
    products = []
    
    query_count = """{ products(search: "", pageSize: 1, currentPage: 1) { total_count } }"""
    try:
        res = requests.post(url, json={'query': query_count}, headers={'User-Agent': 'Mozilla/5.0'})
        total_count = res.json()['data']['products']['total_count']
    except Exception as e:
        print("Error getting count:", e)
        return []

    print(f"Total products: {total_count}")
    
    page_size = 50
    total_pages = math.ceil(total_count / page_size)
    
    for page in range(1, total_pages + 1):
        print(f"Fetching page {page}/{total_pages}...")
        query = f"""
        {{
          products(search: "", pageSize: {page_size}, currentPage: {page}) {{
            items {{
              id
              name
              stock_status
              url_key
              sku
              image {{ url }}
              categories {{ name }}
              price_range {{
                minimum_price {{
                  regular_price {{ value }}
                  final_price {{ value }}
                }}
              }}
            }}
          }}
        }}
        """
        try:
            res = requests.post(url, json={'query': query}, headers={'User-Agent': 'Mozilla/5.0'})
            data = res.json()
            if 'data' in data and 'products' in data['data']:
                items = data['data']['products']['items']
                products.extend(items)
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            
    return products

def clean_text(text):
    if not text: return ""
    # Remove Arabic characters and stray marks
    text = re.sub(r'[\u0600-\u06FF]+', '', text)
    # Remove multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_name(title):
    # Shorter name: usually before the first dash or comma, or just remove variant noise
    name = title.split(' - ')[0].split(' , ')[0].split(' / ')[0]
    # Remove common variant noise
    name = re.sub(r'\b(Silver|Black|Stainless Steel|White|Grey|Red|Blue|Gold|Matt|Inverter|Direct Drive)\b', '', name, flags=re.IGNORECASE).strip()
    return name if name else title

def standardize_category(cats):
    if not cats: return 'home > appliances', 'uncategorized'
    names = [c['name'].lower() for c in cats]
    combined = " ".join(names)
    sub = cats[-1]['name']
    
    if any(k in combined for k in ['tv', 'television']): return 'electronics > tvs', sub
    if any(k in combined for k in ['wash', 'laundry', 'dishwasher']): return 'home > laundry', sub
    if any(k in combined for k in ['cook', 'oven', 'microwave', 'fryer', 'mixer', 'blender', 'food processor']): return 'home > kitchenware', sub
    if any(k in combined for k in ['cool', 'air', 'conditioner', 'fan', 'heater', 'fridge', 'refrigerator', 'freezer', 'cooler']): return 'home > appliances', sub
    
    return 'home > appliances', sub

def extract_weight_unit(title):
    # Look for liters, kgs, watts, cm, etc.
    patterns = [
        r'(\d+(?:\.\d+)?)\s*(Liters?|L|Kgs?|Kg|cm|Watts?|W|Bars?|Gallons?|ml|g)\b',
        r'(\d+)\s*(?:"|inch|inches)\b'
    ]
    for p in patterns:
        match = re.search(p, title, re.IGNORECASE)
        if match:
            val = match.group(1)
            unit = match.group(2).lower() if len(match.groups()) > 1 else "inch"
            return f"{val} {unit}"
    return ""

def extract_ram_storage(title):
    # Mostly for electronics/mobiles if they exist
    ram = re.search(r'(\d+)\s*(GB|MB)\s*RAM', title, re.IGNORECASE)
    storage = re.search(r'(\d+)\s*(GB|TB)\s*(Storage|SSD|HDD|Memory)', title, re.IGNORECASE)
    
    ram_val = ram.group(0) if ram else ""
    storage_val = storage.group(0) if storage else ""
    
    # Also catch patterns like 8/256
    pair = re.search(r'\b(\d+)/(\d+)\b', title)
    if pair and not ram_val:
        ram_val = f"{pair.group(1)}GB"
        storage_val = f"{pair.group(2)}GB"
        
    return ram_val, storage_val

def process_and_save(raw_products):
    columns = [
        "title", "name", "product_current_price", "product_old_price", "product_discount", 
        "product_url", "product_image_url", "product_seller", "product_availability", 
        "product_category", "product_subcategory", "product_unit", "product_weight", 
        "scraping_time", "timestamp_timezone", "product_brand", "product_ram", "product_storage"
    ]
    
    cairo_tz = pytz.timezone('Africa/Cairo')
    now = datetime.now(cairo_tz)
    scraping_time = now.strftime('%Y-%m-%d %H:%M:%S')
    
    processed = []
    for item in raw_products:
        raw_title = item.get('name', '').strip()
        if not raw_title: continue
        
        title = clean_text(raw_title)
        name = extract_name(title)
        
        try:
            current_price = item['price_range']['minimum_price']['final_price']['value']
            old_price = item['price_range']['minimum_price']['regular_price']['value']
        except: continue
            
        if current_price is None: continue
            
        discount = ""
        if old_price and old_price > current_price:
            discount = f"{((old_price - current_price) / old_price) * 100:.3f}%"
        else:
            old_price = ""
            
        url = f"https://fresh.com.eg/en/product/{item.get('url_key', '')}"
        image_url = item.get('image', {}).get('url', '')
        availability = 'in_stock' if item.get('stock_status') == 'IN_STOCK' else 'out_of_stock'
        
        cat, subcat = standardize_category(item.get('categories', []))
        weight_unit = extract_weight_unit(raw_title)
        ram, storage = extract_ram_storage(raw_title)
        
        row = {
            "title": title,
            "name": name,
            "product_current_price": current_price,
            "product_old_price": old_price,
            "product_discount": discount,
            "product_url": url,
            "product_image_url": image_url,
            "product_seller": "Fresh",
            "product_availability": availability,
            "product_category": cat,
            "product_subcategory": subcat,
            "product_unit": "", 
            "product_weight": weight_unit,
            "scraping_time": scraping_time,
            "timestamp_timezone": "Africa/Cairo",
            "product_brand": "Fresh",
            "product_ram": ram,
            "product_storage": storage
        }
        processed.append(row)
        
    # Final cleanup of nulls/broken data
    processed = [r for r in processed if r['title'] and r['product_current_price']]
    
    print(f"Final count: {len(processed)}")
    
    with open('fresh_products.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(processed)
        
    with open('fresh_products.json', 'w', encoding='utf-8') as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    raw = get_product_data()
    process_and_save(raw)
    print("Cleaned data saved.")
