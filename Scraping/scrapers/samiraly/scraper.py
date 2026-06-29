import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import time
import concurrent.futures
from utils import *

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def scrape_product(url):
    # Same implementation as before, but return data directly
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code != 200:
            return None, f"Status {response.status_code}"
            
        if response.encoding is None or response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        json_ld_elem = soup.select_one('script[type="application/ld+json"][data-source="custom_productjsonld"]')
        json_data = {}
        if json_ld_elem:
            try: json_data = json.loads(json_ld_elem.string)
            except: pass
        
        ga4_script = soup.find("script", string=re.compile("item_category"))
        ga4_cats = []
        if ga4_script:
            try:
                cat1 = re.search(r'"item_category":"([^"]+)"', ga4_script.string)
                cat2 = re.search(r'"item_category2":"([^"]+)"', ga4_script.string)
                cat3 = re.search(r'"item_category3":"([^"]+)"', ga4_script.string)
                if cat1: ga4_cats.append(cat1.group(1))
                if cat2: ga4_cats.append(cat2.group(1))
                if cat3: ga4_cats.append(cat3.group(1))
            except: pass
            
        meta_title = soup.select_one('meta[property="og:title"]')
        meta_image = soup.select_one('meta[property="og:image"]')
        meta_price = soup.select_one('meta[property="product:price:amount"]')
        
        title = ""
        if json_data.get("name"): title = json_data.get("name")
        elif meta_title and meta_title.get("content"): title = meta_title.get("content")
        elif soup.select_one("h1.page-title span"): title = soup.select_one("h1.page-title span").get_text(strip=True)
        
        title = clean_text(title)
        if not title: return None, "No title"
        
        name = title.split(" – ")[0] if " – " in title else title
        name = name.split(" - ")[0]
        
        current_price = normalize_price(json_data.get("offers", {}).get("price") or (meta_price["content"] if meta_price else "") or 0)
        old_price_elem = soup.select_one(".price-wrapper[data-price-type='oldPrice'] .price")
        old_price = normalize_price(old_price_elem.get_text(strip=True) if old_price_elem else "")
        discount = calculate_discount(old_price, current_price)
        
        product_url = url
        image_url = json_data.get("image") or (meta_image["content"] if meta_image else "")
        seller = "Samir & Aly"
        availability_str = json_data.get("offers", {}).get("availability", "")
        availability = "in_stock" if "InStock" in availability_str else "out_of_stock"
        
        if not ga4_cats:
            breadcrumbs = soup.select(".breadcrumbs .item")
            ga4_cats = [b.get_text(strip=True) for b in breadcrumbs if b.get_text(strip=True).lower() != "home"]
            
        product_category, product_subcategory = standardize_category(ga4_cats)
        
        specs = {}
        attr_rows = soup.select("table#product-attribute-specs-table tr")
        for row in attr_rows:
            th = row.select_one("th"); td = row.select_one("td")
            if th and td: specs[th.get_text(strip=True)] = td.get_text(strip=True)
        
        brand = specs.get("Brand") or json_data.get("brand", {}).get("name") or ""
        ram, storage, weight, unit = extract_specs(title, specs)
        scraping_time, timestamp_timezone = get_now_info()
        
        return {
            "title": title, "name": name, "product_current_price": current_price,
            "product_old_price": old_price if old_price else "", "product_discount": discount,
            "product_url": product_url, "product_image_url": image_url, "product_seller": seller,
            "product_availability": availability, "product_category": product_category,
            "product_subcategory": product_subcategory, "product_unit": unit, "product_weight": weight,
            "scraping_time": scraping_time, "timestamp_timezone": timestamp_timezone,
            "product_brand": brand, "product_ram": ram, "product_storage": storage
        }, None
    except Exception as e:
        return None, str(e)

def process_url(item):
    if item["status"] != "pending":
        return None
    data, error = scrape_product(item["url"])
    if data:
        item["status"] = "done"
        return data
    else:
        item["status"] = "error"
        item["error"] = error
        return None

def run_multi_scraper(threads=10, batch_size=100):
    if not os.path.exists("todo_products.csv"):
        print("Run discovery first.")
        return
        
    with open("todo_products.csv", "r", encoding="utf-8") as f:
        todo_list = list(csv.DictReader(f))
        
    pending = [item for item in todo_list if item["status"] == "pending"]
    print(f"Pending products: {len(pending)}")
    
    keys = ["title", "name", "product_current_price", "product_old_price", "product_discount", "product_url", "product_image_url", "product_seller", "product_availability", "product_category", "product_subcategory", "product_unit", "product_weight", "scraping_time", "timestamp_timezone", "product_brand", "product_ram", "product_storage"]
    output_file = "samir_and_aly_products.csv"
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        for i in range(0, len(pending), batch_size):
            batch = pending[i:i+batch_size]
            results = list(executor.map(process_url, batch))
            valid_results = [r for r in results if r]
            
            # Append results
            file_exists = os.path.exists(output_file)
            with open(output_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                if not file_exists: writer.writeheader()
                writer.writerows(valid_results)
            
            # Save progress in todo
            with open("todo_products.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["url", "category", "status", "error"])
                writer.writeheader()
                writer.writerows(todo_list)
                
            print(f"Batch {i//batch_size + 1} finished. Scraped {len(valid_results)} products.")
            time.sleep(2)

if __name__ == "__main__":
    run_multi_scraper(threads=15, batch_size=50)
