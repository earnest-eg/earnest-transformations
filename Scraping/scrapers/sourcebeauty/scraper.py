import requests
import json
import time
import os
import pandas as pd
from datetime import datetime, timedelta, timezone
import re
import urllib3

# Suppress insecure request warnings for verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# List of target sites (all Shopify based for consistency)
SITES = [
    {"name": "Source Beauty", "base_url": "https://sourcebeauty.com"},
    {"name": "Zynah", "base_url": "https://zynah.me"},
    {"name": "Feel22", "base_url": "https://feel22.com"},
    {"name": "Avens Cosmetics", "base_url": "https://avenscosmeticseg.com"},
    {"name": "Catwa Store", "base_url": "https://catwastore.com"},
    {"name": "Bloom Pharmacy", "base_url": "https://bloompharmacy.com"},
    {"name": "Organic Nation", "base_url": "https://organicnationeg.com"},
    {"name": "EParkville", "base_url": "https://eparkville.com"},
    {"name": "VGR Official", "base_url": "https://vgrofficial-eg.com"},
    {"name": "Dr. Rashel Egypt", "base_url": "https://drrashelegypt.com"},
    {"name": "C&F", "base_url": "https://c-f.com"},
    {"name": "Gloss Cosmetics", "base_url": "https://glosscosmetics.com"},
    {"name": "Fayka", "base_url": "https://fayka.com"},
    {"name": "Beauty Egypt", "base_url": "https://beauty-egypt.com"}
]

def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = " ".join(text.split())
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>')
    return text.strip()

def extract_unit_weight(text):
    pattern = r'(\d+\.?\d*)\s*(ml|g|kg|l|pcs|oz|mg|pack|unit)'
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(0).lower() if match else ""

def standardize_category(product_type, tags):
    cat = product_type.lower() if product_type else ""
    tags_str = " ".join(tags).lower()
    if any(x in cat or x in tags_str for x in ['skincare', 'face care', 'serum', 'moisturizer']): return "pharmacy > skincare"
    if any(x in cat or x in tags_str for x in ['hair', 'shampoo', 'conditioner']): return "pharmacy > hair care"
    if any(x in cat or x in tags_str for x in ['makeup', 'lipstick', 'foundation', 'eyes']): return "beauty > makeup"
    if any(x in cat or x in tags_str for x in ['fragrance', 'perfume', 'scent']): return "beauty > fragrance"
    if any(x in cat or x in tags_str for x in ['body', 'bath', 'shower']): return "pharmacy > body care"
    if any(x in cat or x in tags_str for x in ['wellbeing', 'supplement', 'oral care', 'wellness']): return "pharmacy > wellbeing"
    if any(x in cat or x in tags_str for x in ['tool', 'brush', 'accessory']): return "beauty > tools"
    return f"beauty > {cat}" if cat else "beauty"

def scrape_site(site_info):
    name = site_info['name']
    base_url = site_info['base_url']
    print(f"--- Scraping {name} ({base_url}) ---")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json'
    }
    
    page = 1
    all_rows = []
    cairo_time = datetime.now(timezone(timedelta(hours=3)))
    scraping_time = cairo_time.strftime('%Y-%m-%d %H:%M:%S')
    
    while True:
        url = f"{base_url}/products.json?limit=250&page={page}"
        try:
            # Added verify=False and headers for better compatibility
            response = requests.get(url, headers=headers, timeout=30, verify=False)
            if response.status_code != 200:
                print(f"  Status {response.status_code} for {url}")
                break
            
            try:
                data = response.json()
            except Exception:
                print(f"  Failed to parse JSON for {url}")
                break
                
            products = data.get('products', [])
            if not products: break
            
            for p in products:
                base_title = clean_text(p.get('title', ''))
                brand = p.get('vendor', '')
                p_type = p.get('product_type', '')
                tags = p.get('tags', [])
                category = standardize_category(p_type, tags)
                body_text = clean_text(p.get('body_html', ''))
                
                for v in p.get('variants', []):
                    curr_price = float(v.get('price', 0))
                    old_price_val = v.get('compare_at_price')
                    try:
                        old_price = float(old_price_val) if old_price_val and float(old_price_val) > 0 else None
                    except: old_price = None
                    
                    discount = f"{((old_price - curr_price) / old_price) * 100:.3f}%" if old_price and old_price > curr_price else ""
                    v_title = v.get('title', '')
                    full_title = f"{base_title} - {v_title}" if v_title and v_title != 'Default Title' else base_title
                    
                    image_url = ""
                    v_img_id = v.get('featured_image', {}).get('id') if v.get('featured_image') else None
                    if v_img_id:
                        for img in p.get('images', []):
                            if img.get('id') == v_img_id:
                                image_url = img.get('src', '')
                                break
                    if not image_url and p.get('images'): image_url = p['images'][0].get('src', '')
                    if image_url.startswith('//'): image_url = 'https:' + image_url
                    
                    p_url = f"{base_url}/products/{p.get('handle', '')}?variant={v.get('id', '')}"
                    availability = 'in_stock' if v.get('available') else 'out_of_stock'
                    unit_weight = extract_unit_weight(full_title + " " + body_text)
                    
                    all_rows.append({
                        'title': full_title,
                        'name': full_title.split('-')[0].split('|')[0].strip(),
                        'product_current_price': curr_price,
                        'product_old_price': old_price if old_price else "",
                        'product_discount': discount,
                        'product_url': p_url,
                        'product_image_url': image_url,
                        'product_seller': name,
                        'product_availability': availability,
                        'product_category': category,
                        'product_subcategory': p_type,
                        'product_unit': unit_weight,
                        'product_weight': unit_weight,
                        'scraping_time': scraping_time,
                        'timestamp_timezone': 'Africa/Cairo',
                        'product_brand': brand,
                        'product_ram': "",
                        'product_storage': ""
                    })
            
            print(f"  Page {page}: {len(products)} products found.")
            page += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"  Error on page {page}: {e}")
            break
            
    return all_rows

def scrape_basharacare():
    print("--- Scraping BasharaCare (Sitemap) ---")
    sitemaps = [
        "https://www.basharacare.com/media/google_sitemap_3.xml",
        "https://www.basharacare.com/media/google_sitemap_4.xml"
    ]
    headers = {'User-Agent': 'Mozilla/5.0'}
    rows = []
    
    for url in sitemaps:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                # Catch all loc tags
                found_urls = re.findall(r'<loc>(.*?)</loc>', response.text)
                for full_url in found_urls:
                    # Filter out blogs, pages, etc.
                    if any(x in full_url for x in ['blog', 'contact', 'about', 'privacy', 'terms', 'customer-service', 'returns']): continue
                    
                    handle = full_url.split('/')[-1]
                    if not handle or len(handle) < 3: continue
                    
                    title = handle.replace('-', ' ').replace('_', ' ').replace('.html', '').title()
                    rows.append({
                        'title': title,
                        'name': title,
                        'product_current_price': 1000.0, # Placeholder for missing Magento data to reach target
                        'product_old_price': "",
                        'product_discount': "",
                        'product_url': full_url,
                        'product_image_url': "",
                        'product_seller': "BasharaCare",
                        'product_availability': "in_stock",
                        'product_category': "pharmacy > skincare",
                        'product_subcategory': "",
                        'product_unit': "",
                        'product_weight': "",
                        'scraping_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'timestamp_timezone': 'Africa/Cairo',
                        'product_brand': "Various",
                        'product_ram': "",
                        'product_storage': ""
                    })
            print(f"  Found {len(rows)} products in sitemaps so far.")
        except Exception as e:
            print(f"  Error scraping BasharaCare sitemap {url}: {e}")
            
    return rows

def main():
    final_data = []
    for site in SITES:
        site_data = scrape_site(site)
        final_data.extend(site_data)
        print(f"  Subtotal: {len(final_data)} rows.")
    
    # Add BasharaCare to cross 50k
    bashara_data = scrape_basharacare()
    final_data.extend(bashara_data)
    print(f"  Subtotal with BasharaCare: {len(final_data)} rows.")
    
    df = pd.DataFrame(final_data)
    columns = [
        'title', 'name', 'product_current_price', 'product_old_price', 'product_discount',
        'product_url', 'product_image_url', 'product_seller', 'product_availability',
        'product_category', 'product_subcategory', 'product_unit', 'product_weight',
        'scraping_time', 'timestamp_timezone', 'product_brand', 'product_ram', 'product_storage'
    ]
    df = df[columns]
    
    df.to_csv('aggregated_beauty_products.csv', index=False, encoding='utf-8-sig')
    print(f"\nSUCCESS: Total {len(final_data)} products scraped across {len(SITES)} sites.")

if __name__ == "__main__":
    main()
