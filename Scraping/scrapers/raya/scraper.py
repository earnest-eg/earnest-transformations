import requests
import csv
import time
import re
import json

URL = "https://api-rayashop.global.ssl.fastly.net/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

PAGE_SIZE = 100
TARGET_ROWS = 25000  # Aim for over 20,000

QUERY_TEMPLATE = """
query ($categoryId: String!, $pageSize: Int!, $currentPage: Int!) {
  products(
    filter: { category_id: { eq: $categoryId } }
    pageSize: $pageSize
    currentPage: $currentPage
  ) {
    total_count
    items {
      name
      url_key
      price_range {
        minimum_price {
          regular_price {
            value
          }
          final_price {
            value
          }
          discount {
            percent_off
          }
        }
      }
      image {
        url
      }
    }
  }
}
"""

def get_all_categories(data):
    categories = {}
    def extract_cats(cat_list):
        for cat in cat_list:
            categories[cat['id']] = cat['name']
            if 'children' in cat and cat['children']:
                extract_cats(cat['children'])
    
    if 'data' in data and 'categoryList' in data['data']:
        extract_cats(data['data']['categoryList'])
    return categories

def parse_title(title):
    name = title
    specs = ""
    color = ""
    
    if " - " in title:
        parts = title.rsplit(" - ", 1)
        name_specs = parts[0].strip()
        color = parts[1].strip()
    else:
        name_specs = title.strip()
        
    spec_pattern = re.compile(r"(Dual SIM|Single SIM|\b\d+\s*(?:GB|TB|MB)\b|\b\d+\s*(?:KG|Liters?|L|W|Watt|Hz|mAh)\b|\bCore\s*i\d\b|\bRyzen\s*\d\b|\b\d+(?:\.\d+)?\s*(?:Inch|\"|cm)\b|\b4K\b|\b8K\b|Smart TV|Wi-Fi|Bluetooth)", re.IGNORECASE)
    
    match = spec_pattern.search(name_specs)
    if match:
        split_index = match.start()
        name = name_specs[:split_index].strip()
        name = name.rstrip(",- ")
        specs = name_specs[split_index:].strip()
    else:
        if "," in name_specs:
            parts = name_specs.split(",", 1)
            name = parts[0].strip()
            specs = parts[1].strip()
        else:
            name = name_specs
            
    return name, specs, color

def fetch_products(category_id, page):
    variables = {
        "categoryId": str(category_id),
        "pageSize": PAGE_SIZE,
        "currentPage": page
    }
    try:
        response = requests.post(URL, headers=HEADERS, json={"query": QUERY_TEMPLATE, "variables": variables}, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None

def process_product(product, category_name):
    title = product.get("name", "N/A")
    name, specs, color = parse_title(title)
    
    price_info = product.get("price_range", {}).get("minimum_price", {})
    current_price = price_info.get("final_price", {}).get("value", "N/A")
    old_price = price_info.get("regular_price", {}).get("value", "N/A")
    discount_val = price_info.get("discount", {}).get("percent_off", 0)
    discount = f"{discount_val}%" if discount_val else "0%"
    
    url_key = product.get("url_key", "")
    url = f"https://www.rayashop.com/en/{url_key}.html" if url_key else "N/A"
    img_url = product.get("image", {}).get("url", "N/A")
    
    # columns: title, current_price, old_price, discount, url, category, name, color, Specifications, img_URL
    return [title, current_price, old_price, discount, url, category_name, name, color, specs, img_url]

def main():
    # Load categories
    try:
        with open("categories.json", "r", encoding="utf-8") as f:
            cat_data = json.load(f)
        all_categories = get_all_categories(cat_data)
        print(f"Loaded {len(all_categories)} categories.")
    except Exception as e:
        print(f"Failed to load categories: {e}")
        return

    total_found = 0
    
    with open("rayashop_massive_dataset.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "current_price", "old_price", "discount", "url", "category", "name", "color", "Specifications", "img_URL"])
        
        for category_id, category_name in all_categories.items():
            if total_found >= TARGET_ROWS:
                break
                
            page = 1
            while True:
                data = fetch_products(category_id, page)
                if not data or "data" not in data or not data["data"]["products"]:
                    break
                
                items = data["data"]["products"].get("items", [])
                if not items:
                    break
                
                for item in items:
                    row = process_product(item, category_name)
                    writer.writerow(row)
                    total_found += 1
                
                total_count = data["data"]["products"].get("total_count", 0)
                if page * PAGE_SIZE >= total_count or total_found >= TARGET_ROWS:
                    break
                
                page += 1
                time.sleep(0.05)
                
            print(f"Category: {category_name} - Collected so far: {total_found}")
                
    print(f"\nScraping complete. Total products collected: {total_found}")
    print("Data saved to rayashop_massive_dataset.csv")

if __name__ == "__main__":
    main()
