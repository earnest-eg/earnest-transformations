"""
Baby Island Egypt - Full Product Scraper
Goal: Scrape ALL products from https://www.babyislandeg.com/shop
"""

import asyncio
import aiohttp
import requests
import csv
import json
import re
import os
import time
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BASE_URL = 'https://www.babyislandeg.com'
WORK_DIR = r'B:\depi\scraping\baby island'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
TIMEOUT = aiohttp.ClientTimeout(total=120)

TARGET_COLUMNS = [
    'title', 'name', 'product_current_price', 'product_old_price',
    'product_discount', 'product_url', 'product_image_url', 'product_seller',
    'product_availability', 'product_category', 'product_subcategory',
    'product_unit', 'product_weight', 'scraping_time', 'timestamp_timezone',
    'product_brand', 'product_ram', 'product_storage'
]

# ---- Phase 1: Discover all product URLs ----

def discover_product_urls():
    """Collect all product URLs from sitemap and shop pages."""
    all_urls = set()

    # 1. Sitemap
    try:
        r = requests.get(f'{BASE_URL}/sitemap.xml', headers=HEADERS, timeout=30)
        if r.status_code == 200:
            urls = re.findall(r'<loc>(https?://www\.babyislandeg\.com/shop/[^<]+)</loc>', r.text)
            # Filter out non-product pages
            skip_patterns = ['/shop/category/', '/shop/page/', '/shop/cart', '/shop/wishlist']
            for u in urls:
                if not any(p in u for p in skip_patterns):
                    all_urls.add(u)
            print(f'Sitemap: found {len(urls)} shop URLs, {len(all_urls)} unique products')
    except Exception as e:
        print(f'Sitemap error: {e}')

    # 2. Shop pages (pagination)
    for page_num in range(1, 100):
        if page_num == 1:
            url = f'{BASE_URL}/shop'
        else:
            url = f'{BASE_URL}/shop/page/{page_num}'
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, 'lxml')
            items = soup.select('div.oe_product')
            if not items:
                break
            for item in items:
                a = item.find('a', class_='oe_product_image_link')
                if a:
                    href = a.get('href', '')
                    if href:
                        full_url = urljoin(BASE_URL, href)
                        all_urls.add(full_url)
            print(f'Page {page_num}: {len(items)} items, total: {len(all_urls)}')
        except Exception as e:
            print(f'Page {page_num} error: {e}')
            break
        # Small delay to be polite
        time.sleep(0.5)

    print(f'\nTotal unique product URLs discovered: {len(all_urls)}')
    return all_urls


# ---- Phase 2: Scrape individual product pages ----

async def fetch_product_page(session, url, semaphore, retries=3):
    """Fetch a product page with retry logic."""
    async with semaphore:
        for attempt in range(retries):
            try:
                async with session.get(url, timeout=TIMEOUT) as response:
                    if response.status == 200:
                        html = await response.text()
                        return html
                    elif response.status == 429:
                        wait = 5 * (attempt + 1)
                        await asyncio.sleep(wait)
                    else:
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < retries - 1:
                    wait = 3 * (attempt + 1)
                    await asyncio.sleep(wait)
                else:
                    return None
        return None


def parse_product_page(html, url):
    """Parse a product page HTML and extract structured data."""
    soup = BeautifulSoup(html, 'lxml')
    data = {}

    # Title
    title_el = soup.find('h1')
    if not title_el:
        title_el = soup.find('h2', class_='o_wsale_products_item_title')
    if title_el:
        data['title'] = title_el.get_text(strip=True)
    else:
        data['title'] = ''

    # Price - look for different patterns
    price_el = soup.select_one('.product_price [data-oe-type="monetary"]')
    if not price_el:
        price_el = soup.select_one('span[data-oe-type="monetary"]')

    current_price = None
    old_price = None

    if price_el:
        val_el = price_el.find('span', class_='oe_currency_value')
        if val_el:
            try:
                current_price = float(val_el.get_text(strip=True).replace(',', ''))
            except ValueError:
                current_price = None
    else:
        # Try alternative price selectors
        price_div = soup.find('div', class_='product_price')
        if price_div:
            for span in price_div.find_all('span', class_='oe_currency_value'):
                try:
                    val = float(span.get_text(strip=True).replace(',', ''))
                    # Determine if this is old or current based on context
                    parent = span.find_parent(['del', 'ins', 'span'])
                    if parent and parent.name == 'del':
                        old_price = val
                    else:
                        if current_price is None:
                            current_price = val
                except ValueError:
                    pass

    # Old price from del element
    del_el = soup.select_one('del[aria-label="Original price"]')
    if del_el:
        val_el = del_el.find('span', class_='oe_currency_value')
        if val_el:
            try:
                old_price = float(val_el.get_text(strip=True).replace(',', ''))
            except ValueError:
                pass

    data['product_current_price'] = current_price
    data['product_old_price'] = old_price

    # Discount
    if current_price and old_price and old_price > current_price:
        data['product_discount'] = round(((old_price - current_price) / old_price) * 100, 3)
    else:
        data['product_discount'] = ''

    # Product URL
    data['product_url'] = url

    # Image URL
    img_el = soup.select_one('.o_wsale_product_images_main img.img-fluid')
    if not img_el:
        img_el = soup.select_one('img[itemprop="image"]')
    if not img_el:
        img_el = soup.find('img', class_='oe_product_image_img')
    if img_el:
        src = img_el.get('src', '')
        if src and not src.startswith('http'):
            src = urljoin(BASE_URL, src)
        data['product_image_url'] = src
    else:
        data['product_image_url'] = ''

    # Seller
    data['product_seller'] = 'Baby Island Egypt'

    # Availability
    stock_el = soup.select_one('.o_wsale_product_availability_info')
    if stock_el:
        text = stock_el.get_text(strip=True).lower()
        if 'in stock' in text or 'available' in text:
            data['product_availability'] = 'in_stock'
        elif 'out of stock' in text or 'unavailable' in text:
            data['product_availability'] = 'out_of_stock'
        else:
            data['product_availability'] = 'in_stock'
    else:
        # Check if "Add to Cart" button exists
        cart_btn = soup.select_one('a[href*="add_to_cart"], button[title*="Add to cart"]')
        if cart_btn:
            data['product_availability'] = 'in_stock'
        else:
            data['product_availability'] = ''

    # Category & Subcategory from breadcrumbs
    breadcrumb = soup.select('.breadcrumb a, nav[aria-label="breadcrumb"] a, ol.breadcrumb a')
    categories = []
    for a in breadcrumb:
        text = a.get_text(strip=True)
        if text and text.lower() not in ['home', 'shop', 'products']:
            categories.append(text)

    # Also check for category in the header area
    cat_links = soup.select('a[href*="/shop/category/"]')
    for a in cat_links:
        text = a.get_text(strip=True)
        if text and text not in categories:
            categories.append(text)

    if categories:
        data['product_subcategory'] = categories[-1] if len(categories) >= 1 else ''
        data['product_category'] = ' > '.join(categories)
    else:
        data['product_category'] = ''
        data['product_subcategory'] = ''

    # Brand from specifications
    brand = ''
    specs_section = soup.find('table', class_='table')
    if not specs_section:
        specs_section = soup.find('div', id='specs')
    if not specs_section:
        specs_section = soup.find('div', string=re.compile(r'Specifications', re.I))
        if specs_section:
            specs_section = specs_section.find_parent('div')

    # Try to find brand in any specification table
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                if 'brand' in label:
                    brand = value
                    break

    # Brand from attributes/specs in product page
    if not brand:
        attr_labels = soup.find_all(['div', 'span', 'th'], string=re.compile(r'^Brand$', re.I))
        for label in attr_labels:
            parent = label.find_parent(['div', 'tr', 'li'])
            if parent:
                val = parent.find(['div', 'span', 'td'])
                if val and val != label:
                    brand = val.get_text(strip=True)
                    break

    # Brand from JSON-LD
    if not brand:
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                ld = json.loads(script.string)
                if isinstance(ld, dict) and 'brand' in ld:
                    brand = ld['brand'].get('name', '') if isinstance(ld['brand'], dict) else str(ld['brand'])
                    break
            except:
                pass

    # Brand from title (fallback)
    if not brand:
        title_lower = data['title'].lower()
        known_brands = ['belecoo', 'kidilo', 'chicco', 'graco', 'joie', 'junior', 'umbrella',
                       'kinderkraft', 'mastela', 'lequeen', 'infantino', 'safari', 'true baby',
                       'canpol', 'lovi', 'philips avent', 'tiibaby', 'bubbles', 'art',
                       'haohao', 'haoshuo', 'aimile', 'seebaby', 'bestbaby', 'shenma',
                       'boyi', 'care me', 'disney', 'poppy papa', 'coolbaby', 'toimoys',
                       'hunger', 'petit bebe', 'valdera', 'aiebao', 'kangaro', 'battota']
        for b in known_brands:
            if b in title_lower:
                brand = b.title()
                break

    data['product_brand'] = brand

    # Extract RAM, Storage from title/specs
    title_text = data['title']
    spec_text = ''

    # RAM
    ram_match = re.search(r'(\d+)\s*GB\s*(RAM|ram)', title_text, re.I)
    if ram_match:
        data['product_ram'] = ram_match.group(0)
    else:
        data['product_ram'] = ''

    # Storage
    storage_match = re.search(r'(\d+)\s*(GB|TB)\s*(SSD|HDD|storage|Storage)?', title_text, re.I)
    if storage_match:
        data['product_storage'] = storage_match.group(0)
    else:
        data['product_storage'] = ''

    # Unit - try to extract from title
    unit_match = re.search(r'(\d+\s*(pcs|pc|pieces|pack|set|in\s*1|ml|l|g|kg))', title_text, re.I)
    if unit_match:
        data['product_unit'] = unit_match.group(1)
    else:
        data['product_unit'] = ''

    # Weight
    weight_match = re.search(r'(\d+\.?\d*\s*(kg|g|l|ml|oz|lb))', title_text, re.I)
    if weight_match:
        data['product_weight'] = weight_match.group(0)
    else:
        data['product_weight'] = ''

    # Name (shorter version without color/variant noise)
    name = data['title']
    # Remove variant suffixes like "(Black)", "(Blue)"
    name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
    name = re.sub(r'\s*[-–—]\s*[^-–—]*$', '', name)
    data['name'] = name.strip()

    # Timestamps
    data['scraping_time'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    data['timestamp_timezone'] = 'Africa/Cairo'

    return data


def standardize_category(cat, subcat, title, brand):
    """Standardize messy categories into clean hierarchy."""
    mapping = {
        'kids toys': 'baby products > toys',
        'baby fun time': 'baby products > toys',
        'baby sleeping time': 'baby products > bedding',
        'baby care time': 'baby products > care',
        'baby going-out time': 'baby products > strollers',
        'baby safety time': 'baby products > safety',
        'baby feeding time': 'baby products > feeding',
        'baby clothes': 'baby products > clothing',
        'travel system': 'baby products > strollers',
        'stroller': 'baby products > strollers',
        'car seat': 'baby products > car seats',
        'feeding chair': 'baby products > feeding',
        'diaper bag': 'baby products > bags',
        'bath': 'baby products > bathing',
        'feeding pillow': 'baby products > feeding',
    }

    text_to_check = f'{cat} {subcat} {title}'.lower()

    for key, value in mapping.items():
        if key in text_to_check:
            return value

    # Brand-based categorization
    brand_cats = {
        'kidilo': 'baby products > strollers',
        'chicco': 'baby products > feeding',
        'graco': 'baby products > strollers',
        'joie': 'baby products > strollers',
        'belecoo': 'baby products > strollers',
        'junior': 'baby products > clothing',
        'philips avent': 'baby products > feeding',
        'bubbles': 'baby products > feeding',
        'safari': 'baby products > feeding',
        'true baby': 'baby products > feeding',
        'canpol': 'baby products > feeding',
        'lovi': 'baby products > feeding',
        'mastela': 'baby products > strollers',
        'umbrella': 'baby products > strollers',
    }

    if brand:
        bl = brand.lower()
        for key, value in brand_cats.items():
            if key in bl:
                return value

    return 'baby products > other'


def clean_data(data):
    """Clean and normalize scraped data."""
    # Ensure numeric fields
    for field in ['product_current_price', 'product_old_price']:
        if data.get(field) in [None, 'None', '']:
            data[field] = ''
        elif isinstance(data[field], float):
            data[field] = data[field]
        else:
            try:
                data[field] = float(str(data[field]).replace(',', ''))
            except (ValueError, TypeError):
                data[field] = ''

    # Ensure discount
    if data.get('product_discount') in [None, 'None', '']:
        data['product_discount'] = ''
    elif isinstance(data['product_discount'], (int, float)):
        data['product_discount'] = f'{data["product_discount"]:.3f}%'

    # Standardize availability
    avail = data.get('product_availability', '')
    if avail:
        al = avail.lower()
        if any(w in al for w in ['out', 'unavail', 'sold']):
            data['product_availability'] = 'out_of_stock'
        else:
            data['product_availability'] = 'in_stock'

    # Standardize category
    if not data.get('product_category'):
        data['product_category'] = standardize_category(
            '', '', data.get('title', ''), data.get('product_brand', '')
        )

    return data


async def scrape_product(session, url, semaphore):
    """Scrape a single product page."""
    html = await fetch_product_page(session, url, semaphore)
    if not html:
        return {
            'title': '',
            'name': '',
            'product_current_price': '',
            'product_old_price': '',
            'product_discount': '',
            'product_url': url,
            'product_image_url': '',
            'product_seller': '',
            'product_availability': '',
            'product_category': '',
            'product_subcategory': '',
            'product_unit': '',
            'product_weight': '',
            'scraping_time': '',
            'timestamp_timezone': '',
            'product_brand': '',
            'product_ram': '',
            'product_storage': ''
        }

    data = parse_product_page(html, url)
    data = clean_data(data)
    return data


async def scrape_all_products(product_urls, max_concurrent=5):
    """Scrape all product pages with concurrency control."""
    semaphore = asyncio.Semaphore(max_concurrent)
    connector = aiohttp.TCPConnector(limit=10, force_close=True)

    all_results = []
    batch_size = 50

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        urls_list = list(product_urls)
        for i in range(0, len(urls_list), batch_size):
            batch = urls_list[i:i + batch_size]
            tasks = [scrape_product(session, url, semaphore) for url in batch]
            results = await asyncio.gather(*tasks)
            all_results.extend(results)

            # Save progress after each batch
            if len(all_results) % 50 == 0:
                save_csv(all_results, os.path.join(WORK_DIR, 'scraped_products_partial.csv'))
                print(f'Scraped {len(all_results)}/{len(urls_list)} products')

            # Delay between batches to be polite
            await asyncio.sleep(1)

    return all_results


def save_csv(data_list, filepath):
    """Save scraped data to CSV."""
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        for row in data_list:
            writer.writerow({k: row.get(k, '') for k in TARGET_COLUMNS})
    print(f'Saved {len(data_list)} rows to {filepath}')


def save_json(data_list, filepath):
    """Save scraped data to JSON."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)
    print(f'Saved {len(data_list)} rows to {filepath}')


def validate_data(data_list):
    """Validate scraped data."""
    issues = []
    for i, row in enumerate(data_list):
        # Check column count
        cols = len(row)
        if cols != 18:
            issues.append(f'Row {i}: {cols} columns (expected 18)')

        # Check required fields
        if not row.get('title') and not row.get('product_url'):
            issues.append(f'Row {i}: Missing title and URL')

        # Check prices
        cp = row.get('product_current_price', '')
        if cp != '' and not isinstance(cp, str) and cp is not None:
            try:
                float(cp)
            except (ValueError, TypeError):
                issues.append(f'Row {i}: Invalid current price {cp}')

    if issues:
        print(f'\nValidation issues ({len(issues)}):')
        for issue in issues[:20]:
            print(f'  {issue}')
    else:
        print('\nValidation: All rows passed!')

    return len(issues)


def main():
    """Main scraping pipeline."""
    start_time = time.time()
    print('=' * 60)
    print('Baby Island Egypt - Full Scraper')
    print('=' * 60)

    # Phase 1: Discover URLs
    print('\n[Phase 1] Discovering product URLs...')
    product_urls = discover_product_urls()

    if not product_urls:
        print('ERROR: No product URLs found!')
        return

    # Save todo_products.csv
    todo_path = os.path.join(WORK_DIR, 'todo_products.csv')
    with open(todo_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['url', 'status'])
        for url in product_urls:
            writer.writerow([url, 'pending'])
    print(f'Saved {len(product_urls)} URLs to todo_products.csv')

    # Phase 2: Scrape products
    print(f'\n[Phase 2] Scraping {len(product_urls)} products...')
    results = asyncio.run(scrape_all_products(product_urls, max_concurrent=3))

    successful = [r for r in results if r.get('title')]
    print(f'\nScraped {len(successful)}/{len(product_urls)} products successfully')

    # Phase 3: Clean & Standardize
    print('\n[Phase 3] Standardizing categories...')
    for row in results:
        row['product_category'] = standardize_category(
            row.get('product_category', ''),
            row.get('product_subcategory', ''),
            row.get('title', ''),
            row.get('product_brand', '')
        )

    # Phase 4: Export
    print('\n[Phase 4] Exporting...')
    csv_path = os.path.join(WORK_DIR, 'babyisland_products.csv')
    json_path = os.path.join(WORK_DIR, 'babyisland_products.json')
    save_csv(results, csv_path)
    save_json(results, json_path)

    # Phase 5: Validate
    print('\n[Phase 5] Validating...')
    validate_data(results)

    elapsed = time.time() - start_time
    print(f'\nTotal time: {elapsed:.1f}s')
    print(f'Products scraped: {len(results)}')
    print(f'Files saved:')
    print(f'  - {csv_path}')
    print(f'  - {json_path}')
    print(f'  - {todo_path}')

    # Print summary stats
    prices = [r['product_current_price'] for r in results if isinstance(r['product_current_price'], (int, float))]
    if prices:
        print(f'\nPrice range: {min(prices):.2f} - {max(prices):.2f} LE (avg: {sum(prices)/len(prices):.2f})')
    brands = set(r['product_brand'] for r in results if r.get('product_brand'))
    print(f'Brands found: {len(brands)}')
    categories = set(r['product_category'] for r in results if r.get('product_category'))
    print(f'Categories: {len(categories)}')


if __name__ == '__main__':
    main()
