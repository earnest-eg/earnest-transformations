import requests
import csv
import time
import json
import os
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = 'https://www.dokkantech.com'
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dokkantech_products.csv')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def fetch_all_products_json():
    """Fetch ALL products from products.json API with deduplication"""
    all_products = {}
    page = 1
    consecutive_empty = 0
    while consecutive_empty < 3:
        url = f'{BASE_URL}/products.json?page={page}&limit=250'
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                print(f'HTTP {r.status_code} on page {page}')
                consecutive_empty += 1
                page += 1
                continue
            data = r.json()
            batch = data.get('products', [])
            if not batch:
                consecutive_empty += 1
                print(f'Page {page}: empty (streak: {consecutive_empty})')
                page += 1
                time.sleep(0.2)
                continue
            consecutive_empty = 0
            for p in batch:
                all_products[p['id']] = p
            print(f'JSON page {page}: {len(batch)} (unique: {len(all_products)})', flush=True)
            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f'Error on page {page}: {e}')
            page += 1
            time.sleep(1)
    return list(all_products.values())

def fetch_all_products_sitemap():
    """Fetch product URLs from sitemap as fallback"""
    r = requests.get(f'{BASE_URL}/sitemap_products_1.xml?from=7524632035477&to=9239145414805', headers=HEADERS, timeout=30)
    urls = re.findall(r'<loc>(https://www\.dokkantech\.com/products/[^<]+)</loc>', r.text)
    print(f'Sitemap URLs found: {len(urls)}')
    return urls

def scrape_product_page(url):
    """Scrape a single product page for price data"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = ''
        price = ''
        compare_price = ''
        category = ''
        
        t = soup.find('title')
        if t: title = t.text.strip()
        
        # Try to find JSON-LD data
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Product':
                            if item.get('name'): title = item['name']
                            if item.get('offers'):
                                offers = item['offers']
                                if isinstance(offers, list):
                                    for o in offers:
                                        if o.get('price'): price = o['price']
                                        if o.get('priceSpecification') and o['priceSpecification'].get('price'):
                                            compare_price = o['priceSpecification']['price']
                                else:
                                    if offers.get('price'): price = offers['price']
                        break
                elif isinstance(data, dict) and data.get('@type') == 'Product':
                    if data.get('name'): title = data['name']
                    if data.get('offers'):
                        offers = data['offers']
                        if offers.get('price'): price = offers['price']
            except:
                pass
        
        # Try meta price
        if not price:
            m = soup.find('meta', property='product:price:amount')
            if m: price = m.get('content', '')
        
        return {'title': title, 'price': price, 'compare_price': compare_price}
    except Exception as e:
        print(f'  Error scraping {url}: {e}')
        return None

def fetch_all_products_html():
    """Fetch products from HTML collection pages"""
    products_map = {}
    collection_urls = [
        f'{BASE_URL}/collections/all?page={p}' for p in range(1, 100)
    ]
    # Add known collection handles from the 185 collections
    # We'll just use the JSON approach which is more reliable
    return products_map

def compute_discount(price, compare_at_price):
    if not compare_at_price:
        return ''
    try:
        price_f = float(price)
        compare_f = float(compare_at_price)
        if compare_f > price_f:
            discount = ((compare_f - price_f) / compare_f) * 100
            return f'{discount:.0f}%'
    except:
        pass
    return ''

def expand_variants(products, source='json'):
    rows = []
    seen = set()
    for p in products:
        title = p.get('title', '')
        product_type = p.get('product_type', '')
        handle = p.get('handle', '')
        product_url = f'{BASE_URL}/products/{handle}'
        tags = p.get('tags', [])
        vendor = p.get('vendor', '')
        category = product_type if product_type else (tags[0] if tags else '')

        variants = p.get('variants', [])
        if not variants:
            # No variants, still add a row
            rows.append({
                'title': title,
                'current_price': '',
                'old_price': '',
                'discount': '',
                'url': product_url,
                'category': category,
                'sku': p.get('handle', ''),
                'variant': 'Default Title',
                'available': 'Yes',
                'vendor': vendor,
                'tags': '|'.join(tags) if tags else ''
            })
            continue

        for v in variants:
            variant_title = v.get('title', 'Default Title')
            price = v.get('price', '')
            compare_at_price = v.get('compare_at_price') or ''
            discount = compute_discount(price, compare_at_price)
            sku = v.get('sku', '')
            available = v.get('available', True)

            full_title = f'{title} - {variant_title}' if variant_title != 'Default Title' else title
            row_key = (p.get('id', product_url), variant_title)
            if row_key in seen:
                continue
            seen.add(row_key)

            rows.append({
                'title': full_title,
                'current_price': price,
                'old_price': compare_at_price,
                'discount': discount,
                'url': product_url,
                'category': category,
                'sku': sku,
                'variant': variant_title,
                'available': 'Yes' if available else 'No',
                'vendor': vendor,
                'tags': '|'.join(tags) if tags else ''
            })
    return rows

def save_csv(rows):
    if not rows:
        print('No data to save!')
        return
    fieldnames = ['title', 'current_price', 'old_price', 'discount', 'url', 'category', 'sku', 'variant', 'available', 'vendor', 'tags']
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f'\nSaved {len(rows)} rows to {OUTPUT_FILE}')

def main():
    print('='*60)
    print('DokkanTech Product Scraper v2')
    print('='*60)
    
    # Method 1: JSON API (primary)
    print('\n[1/2] Fetching from Shopify JSON API...')
    products = fetch_all_products_json()
    print(f'Unique products from JSON API: {len(products)}')
    
    # Method 2: HTML fallback - scrape sitemap URLs that weren't in JSON
    print('\n[2/2] Checking sitemap for additional products...')
    sitemap_urls = fetch_all_products_sitemap()
    json_handles = {f'{BASE_URL}/products/{p["handle"]}' for p in products}
    missing_urls = [u for u in sitemap_urls if u not in json_handles]
    if missing_urls:
        print(f'Found {len(missing_urls)} URLs not in JSON API - scraping individually...')
        for i, url in enumerate(missing_urls[:50]):  # limit to 50
            print(f'  Scraping {i+1}/{len(missing_urls)}...')
            data = scrape_product_page(url)
            if data:
                print(f'    Title: {data["title"][:60]}')
            time.sleep(0.5)
    else:
        print('Sitemap URLs match JSON API - no additional products found.')
    
    rows = expand_variants(products)
    print(f'\nTotal variant rows: {len(rows)}')
    
    save_csv(rows)
    print('\nDone!')

if __name__ == '__main__':
    main()
