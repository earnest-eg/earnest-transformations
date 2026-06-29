import asyncio, json, sys, csv, os, re, time
from datetime import datetime
from urllib.parse import urlparse
sys.stdout.reconfigure(encoding='utf-8')

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

BASE_URL = "https://cairosales.com"
OUTPUT_DIR = "output"
COLUMNS = [
    'title', 'name', 'product_current_price', 'product_old_price',
    'product_discount', 'product_url', 'product_image_url', 'product_seller',
    'product_availability', 'product_category', 'product_subcategory',
    'product_unit', 'product_weight', 'scraping_time', 'timestamp_timezone',
    'product_brand', 'product_ram', 'product_storage'
]

def clean_price(text):
    if not text: return ''
    text = re.sub(r'[^\d.,]', '', text)
    return text.replace(',', '')

def calc_discount(old, curr):
    if not old or not curr: return ''
    try:
        o = float(old.replace(',', ''))
        c = float(curr.replace(',', ''))
        if o > c and o > 0:
            return f"{((o - c) / o) * 100:.3f}%"
    except: pass
    return ''

def extract_brand(title, features_text, url):
    known = ['SAMSUNG','Samsung','LG','BOSCH','Bosch','WHIRLPOOL','Haier','TCL','SONY',
        'Panasonic','SHARP','TOSHIBA','HISENSE','PHILIPS','Xiaomi','Realme','NOKIA',
        'APPLE','DELL','HP','Lenovo','MSI','ACER','ASUS','HUAWEI','OPPO','OnePlus',
        'GREE','Midea','Carrier','MIDEA','FRESH','Fresh','Tornado','Beko','BEKO',
        'Ariston','ZANUSSI','Indesit','CANDY','Gorenje','FAGOR','Kenwood','Moulinex',
        'Tefal','Braun','DeLonghi','KORKMAZ','KARACA','Tramontina','Pasabahce',
        'Luminarc','Pyrex','CASIO','Citizen','G-SHOCK','HUGO BOSS','ZIPPO',
        'INTEX','Bestway','Coleman','Campingaz','JBL','TP-Link','D-Link','Ezviz',
        'APC','Schneider','Black & Decker','DREMEL','Karcher','STANLEY',
        'Oral-B','Beurer','Remington','WAHL','Miele','Smeg','Russell Hobbs',
        'Ariete','SOKANY','SOLAC','UNIONAIRE','UNIVERSAL','White Point','Fulgor',
        'Galanz','Thomson','Simfer','La Germania','Tecnogas','Technogas','Royal Gas',
        'Elica','Jet Air','Franke','AURORA','Riversong','Maxel','Kiriazi','OCY','QCY',
        'IMILAB','Mophie','Pantum','ViewSonic','NORDICTRACK','PRO-FORM','Entercise',
        'Bompani','OKKA','Kumtel','RHEEM','Bradford','ARISTON','Ferroli','Clage',
        'THERMOFLOW','Havells','VARTA','BENZ','CICO','BERGHOFF','NEOFLAM','SILTAL',
        'SYINIX','CAIXUN','TORNADO','HOME','ELBA','UNIONAIRE','UNIVERSAL',
        'BOMANN','GORENJE','FULGOR','HITACHI','TEKNOPATHY','DELONGHI','KENWOOD',
        'MOULINEX','TEFAL','BRAUN','REMINGTON','WAHL','ORAL-B','BEURER','OMRON',
        'SINOCARE','MENEGHETTI','KORKMAZ','KARACA','FISSLER','Whirlpool','Taurus',
        'Black+Decker','HOOVER','Bissell','Rowenta','SEB','Calor','T-FAL',
        'ABOUD','Aboud','BERGEN','BERGHAUS','TOP CHEF','Top Chef','COOKIN',
        'Cookin','EVELIN','Evelin','KORINA','KITCHEN LINE','OCEAN','PURITY',
        'BORCAM','CEM§AN','Cemsan','EKIN','ELZENOUKI','HAMBERG','SOKANY',
        'GOLDEN','FERSEN','Ferrari','MAXEL','ONYX','PENNA','SANDWAY',
        'SILVER','STEEL','TITAN','WOOD & MORE','ZAHRA','ZAHRA','ZINOX']
    
    text = f"{title} {features_text} {url}"
    text_lower = text.lower()
    for brand in sorted(known, key=len, reverse=True):
        if brand.lower() in text_lower:
            return brand
    return ''

STANDARD_CATEGORIES = {
    'tvs-screens': 'electronics > tvs',
    'air-conditioners': 'electronics > air-conditioners',
    'home-theaters-speakers': 'electronics > audio',
    'electronics-tv-accessories': 'electronics > accessories',
    'mobiles-tablets': 'electronics > mobiles',
    'mobile-accessories': 'electronics > mobile-accessories',
    'computer-accessories': 'electronics > computers',
    'gaming-accessories': 'electronics > gaming',
    'refrigerators': 'appliances > refrigerators',
    'freezers': 'appliances > freezers',
    'washers-dryers': 'appliances > washers-dryers',
    'dishwashers': 'appliances > dishwashers',
    'microwaves': 'appliances > microwaves',
    'cookers-ovens': 'appliances > cookers-ovens',
    'kitchen-bath-hoods': 'appliances > hoods',
    'built-in-kitchen-products': 'appliances > built-in',
    'vacuums-steam-cleaners': 'appliances > vacuum-cleaners',
    'water-heaters': 'appliances > water-heaters',
    'water-dispenser': 'appliances > water-dispensers',
    'air-purifiers': 'appliances > air-purifiers',
    'small-appliances': 'appliances > small-appliances',
    'cookware-tableware': 'home > kitchenware',
    'home-decor-furnishings': 'home > furniture',
    'home-accessories': 'home > accessories',
    'home-finishing-construction': 'home > construction',
    'bedding-mattresses': 'home > bedding',
    'home-security-surveillance': 'home > security',
    'safes': 'home > safes',
    'gardening-equipment': 'home > gardening',
    'power-and-hand-tools': 'home > tools',
    'lighters': 'fashion > lighters',
    'watches': 'fashion > watches',
    'bags': 'fashion > bags',
    'skin-hair-care': 'beauty > personal-care',
    'medical-health': 'health > medical',
    'baby-family-care': 'baby > products',
    'treadmills-outdoor-sports': 'sports > equipment',
    'scales': 'home > scales',
    'pet-supplies': 'pet > supplies',
    'music-instruments': 'hobby > music',
    'office-supplies': 'office > supplies',
    'manufacturer': 'brands',
}

class CairoScraper:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.all_urls = {}
        self.all_data = []
    
    async def start_browser(self):
        self.playwright = await async_playwright().start()
        stealth = Stealth()
        stealth.hook_playwright_context(self.playwright)
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", timezone_id="Africa/Cairo",
        )
        self.page = await self.context.new_page()
    
    async def close_browser(self):
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
    
    async def discover_all_categories_and_products(self, max_categories=50):
        """Phase 1: Discover all categories with subcategories and collect product URLs."""
        print("=" * 60)
        print("PHASE 1: CATEGORY & PRODUCT URL DISCOVERY")
        print("=" * 60)
        
        await self.page.goto(f"{BASE_URL}/en/", timeout=90000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        
        # Get all category URLs from homepage navigation
        category_tree = await self.page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="/en/"]');
                const tree = {};
                const seen = new Set();
                
                for (const a of links) {
                    const href = a.href;
                    const text = a.textContent.trim();
                    if (!text || text.length < 2) continue;
                    
                    // Skip non-category links
                    if (href.includes('#') || href.includes('?') || href.includes('/content/') ||
                        href.includes('/help') || href.includes('/my-account') || href.includes('/quick-order') ||
                        href.includes('/order-history') || href.includes('/identity') ||
                        href.includes('/module/') || href.includes('/manufacturer/') ||
                        href.includes('/new-products') || href.includes('/stores') ||
                        href.includes('/addresses') || href.includes('tel:') || href.includes('/ar/') ||
                        href.includes('/https:/') || href.includes('.html')) continue;
                    
                    const cleanHref = href.endsWith('/') ? href : href + '/';
                    if (seen.has(cleanHref)) continue;
                    seen.add(cleanHref);
                    
                    const path = cleanHref.replace('https://cairosales.com/en/', '').replace(/\\/$/, '');
                    if (!path || path.includes('?')) continue;
                    
                    const parts = path.split('/');
                    const topCat = parts[0];
                    
                    if (!tree[topCat]) {
                        tree[topCat] = {name: topCat, url: cleanHref, subcategories: {}};
                    }
                    
                    if (parts.length === 2) {
                        tree[topCat].subcategories[parts[1]] = {
                            name: parts[1],
                            text: text,
                            url: cleanHref
                        };
                    }
                }
                return Object.values(tree);
            }
        """)
        
        # Filter out non-category paths
        BLACKLIST = {'content', 'help', 'identity', 'module', 'my-account', 'quick-order',
                     'order-history', 'stores', 'manufacturer', 'addresses', 'new-products', 'https:'}
        
        categories = [c for c in category_tree if c['name'] not in BLACKLIST]
        
        print(f"Discovered {len(categories)} top-level categories:")
        for cat in categories:
            subs = list(cat['subcategories'].keys())
            print(f"  {cat['name']:35s} ({len(subs)} subs): {', '.join(subs[:5])}")
        
        # For each category, collect product URLs
        total_products = 0
        
        for cat in categories:
            cat_name = cat['name']
            if total_products >= 100000:
                break
            
            print(f"\n{'─'*60}")
            print(f"Category: {cat_name}")
            print(f"{'─'*60}")
            
            # First try the main category page
            main_count = await self.collect_products_from_page(cat['url'], cat_name, '')
            print(f"  Main page: {main_count} new products")
            
            # If few products, also try p=2,3...
            if main_count < 50:
                main_count = await self.collect_products_paginated(cat['url'], cat_name, '')
            
            # Now try each subcategory
            for sub_name, sub_info in cat['subcategories'].items():
                if total_products >= 100000:
                    break
                sub_count = await self.collect_products_from_page(sub_info['url'], cat_name, sub_info['text'])
                if sub_count == 0:
                    sub_count = await self.collect_products_paginated(sub_info['url'], cat_name, sub_info['text'])
            
            total_products = len(self.all_urls)
            print(f"  Running total: {total_products}")
            
            # Save progress
            self.save_todo()
        
        print(f"\n{'='*60}")
        print(f"DISCOVERY COMPLETE: {len(self.all_urls)} unique product URLs")
        print(f"{'='*60}")
        
        return list(self.all_urls.keys())
    
    async def collect_products_from_page(self, url, category, subcategory):
        """Get product URLs from a single category/subcategory page."""
        before = len(self.all_urls)
        
        try:
            await self.page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)
            
            # Get ONLY product links within the product_list UL
            urls = await self.page.evaluate("""
                () => {
                    const list = document.querySelector('ul.product_list');
                    if (!list) return [];
                    const links = list.querySelectorAll('a[href*=".html"]');
                    const seen = new Set();
                    const result = [];
                    for (const a of links) {
                        const href = a.href;
                        if (!seen.has(href) && href.includes('/en/') && 
                            !href.includes('manufacturer') && !href.includes('/content/') &&
                            href.endsWith('.html') && !a.closest('.product-image-container')?.querySelector('.new-box')) {
                            seen.add(href);
                            result.push(href);
                        }
                    }
                    return result;
                }
            """)
            
            # Filter to unique, add to collection
            added = 0
            for u in urls:
                if u not in self.all_urls:
                    self.all_urls[u] = {'category': category, 'subcategory': subcategory, 'page_url': url}
                    added += 1
            
            return added
            
        except Exception as e:
            print(f"    Error on {url}: {e}")
            return 0
    
    async def collect_products_paginated(self, base_url, category, subcategory):
        """Get product URLs from paginated category pages."""
        total_added = 0
        page_num = 1
        
        while page_num <= 200:
            url = f"{base_url}?p={page_num}" if page_num > 1 else base_url
            added = await self.collect_products_from_page(url, category, subcategory)
            
            if added == 0 and page_num > 1:
                break
            total_added += added
            
            page_num += 1
            
            # Safety - stop if no more
            if page_num > 3 and added < 3:
                break
        
        return total_added
    
    def save_todo(self):
        """Save current URL collection."""
        todo_file = os.path.join(OUTPUT_DIR, "todo_products.csv")
        with open(todo_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['url', 'category', 'subcategory', 'status', 'error'])
            for url, info in self.all_urls.items():
                writer.writerow([url, info.get('category',''), info.get('subcategory',''), 'pending', ''])
    
    async def scrape_all_products(self):
        """Phase 2: Scrape all collected product URLs."""
        print("\n" + "=" * 60)
        print("PHASE 2: SCRAPING PRODUCT PAGES")
        print("=" * 60)
        
        urls_list = list(self.all_urls.keys())
        total = len(urls_list)
        print(f"Total to scrape: {total}")
        
        self.all_data = []
        
        for i, url in enumerate(urls_list):
            if i % 25 == 0:
                print(f"  Progress: {i}/{total} (saved: {len(self.all_data)})")
            
            try:
                data = await self.scrape_single_product(url)
                self.all_data.append(data)
            except Exception as e:
                print(f"  Error [{i}]: {str(e)[:60]}")
                self.all_data.append({
                    'title': '', 'name': '', 'product_current_price': '', 'product_old_price': '',
                    'product_discount': '', 'product_url': url, 'product_image_url': '',
                    'product_seller': 'Cairo Sales', 'product_availability': '', 
                    'product_category': self.all_urls.get(url, {}).get('category', ''),
                    'product_subcategory': self.all_urls.get(url, {}).get('subcategory', ''),
                    'product_unit': '', 'product_weight': '',
                    'scraping_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                    'timestamp_timezone': 'Africa/Cairo',
                    'product_brand': '', 'product_ram': '', 'product_storage': ''
                })
            
            # Periodic save
            if len(self.all_data) % 250 == 0:
                self.save_intermediate()
        
        # Final save
        self.save_intermediate()
        print(f"\nScraping complete: {len(self.all_data)} products")
    
    async def scrape_single_product(self, url):
        """Scrape a single product page."""
        await self.page.goto(url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(0.8)
        
        result = await self.page.evaluate("""
            () => {
                const d = {};
                d.title = document.querySelector('h1')?.textContent?.trim() || '';
                
                const priceEl = document.querySelector('#our_price_display');
                d.priceContent = priceEl?.getAttribute?.('content') || '';
                d.priceText = priceEl?.textContent?.trim() || '';
                
                const oldEl = document.querySelector('#old_price_display');
                d.oldPrice = oldEl?.textContent?.trim() || '';
                
                d.discount = document.querySelector('#reduction_percent_display')?.textContent?.trim() || '';
                
                const img = document.querySelector('#bigpic') || document.querySelector('.pb-left-column img');
                d.image = img?.src || '';
                
                const avail = document.querySelector('[itemprop="availability"]');
                d.availHref = avail?.getAttribute?.('href') || '';
                d.availValue = document.querySelector('#availability_value')?.textContent?.trim() || '';
                
                const crumbs = document.querySelectorAll('.breadcrumb a');
                d.breadcrumbs = Array.from(crumbs).map(a => a.textContent.trim()).filter(t => t.length > 0);
                
                const refEl = document.querySelector('#product_reference .editable');
                d.reference = refEl?.getAttribute?.('content') || refEl?.textContent?.trim() || '';
                
                d.desc = document.querySelector('#short_description_content')?.textContent?.trim() || '';
                
                const rows = document.querySelectorAll('.table-data-sheet tr');
                d.features = Array.from(rows).map(tr => {
                    const cells = tr.querySelectorAll('td');
                    return cells.length >= 2 ? {n: cells[0].textContent.trim(), v: cells[1].textContent.trim()} : null;
                }).filter(Boolean);
                
                return d;
            }
        """)
        
        info = self.all_urls.get(url, {})
        
        # Build row
        row = {
            'title': result.get('title', ''),
            'name': result.get('title', ''),
            'product_current_price': result.get('priceContent', '') or clean_price(result.get('priceText', '')),
            'product_old_price': clean_price(result.get('oldPrice', '')),
            'product_discount': '',
            'product_url': url,
            'product_image_url': result.get('image', ''),
            'product_seller': 'Cairo Sales',
            'product_availability': '',
            'product_category': STANDARD_CATEGORIES.get(info.get('category',''), info.get('category','')),
            'product_subcategory': info.get('subcategory', ''),
            'product_unit': '',
            'product_weight': '',
            'scraping_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'timestamp_timezone': 'Africa/Cairo',
            'product_brand': '',
            'product_ram': '',
            'product_storage': ''
        }
        
        # Discount
        if row['product_old_price'] and row['product_current_price']:
            row['product_discount'] = calc_discount(row['product_old_price'], row['product_current_price'])
        if not row['product_discount']:
            raw_disc = result.get('discount', '')
            if raw_disc:
                row['product_discount'] = raw_disc
        
        # Availability
        avail_href = result.get('availHref', '')
        if 'InStock' in avail_href:
            row['product_availability'] = 'in_stock'
        elif 'OutOfStock' in avail_href:
            row['product_availability'] = 'out_of_stock'
        else:
            avail_text = result.get('availValue', '')
            if 'out' in avail_text.lower() or 'no' in avail_text.lower():
                row['product_availability'] = 'out_of_stock'
            elif 'in' in avail_text.lower() or 'avail' in avail_text.lower() or result.get('availHref', ''):
                row['product_availability'] = 'in_stock'
        
        # Brand
        features_text = ' '.join([f.get('n','') + ' ' + f.get('v','') for f in result.get('features', [])])
        all_text = f"{row['title']} {result.get('desc','')} {features_text}"
        row['product_brand'] = extract_brand(row['title'], all_text, url)
        
        # RAM
        ram_m = re.search(r'(\d+)\s*GB\s*(?:RAM|ram|Ram|Ram)', all_text)
        if ram_m: row['product_ram'] = ram_m.group(0)
        
        # Storage
        stor_m = re.search(r'(?:storage|Storage|ROM|rom|internal)[:\s]*(\d+\s*(?:GB|TB|SSD))', all_text)
        if not stor_m: stor_m = re.search(r'(\d+\s*[GT]B)\s*(?:SSD|HDD|storage)', all_text)
        if not stor_m: stor_m = re.search(r'(?:SSD|Hard)[:\s]*(\d+\s*(?:GB|TB))', all_text)
        if stor_m: row['product_storage'] = stor_m.group(1).strip()
        
        # Weight
        wt_m = re.search(r'(\d+[\.\d]*)\s*(kg|Kg|KG|g|lb|L|liter|ml|ton)', all_text)
        if wt_m: row['product_weight'] = f"{wt_m.group(1)} {wt_m.group(2).lower()}"
        
        # Unit
        un_m = re.search(r'(\d+)\s*(pcs|pieces?|pack|units?|set)', all_text, re.I)
        if un_m: row['product_unit'] = f"{un_m.group(1)} {un_m.group(2).lower()}"
        
        return row
    
    def save_intermediate(self):
        filepath = os.path.join(OUTPUT_DIR, "products_intermediate.csv")
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for row in self.all_data:
                writer.writerow({k: row.get(k, '') for k in COLUMNS})
        print(f"  Saved intermediate ({len(self.all_data)} rows)")
    
    def clean_and_export_final(self):
        """Phase 3: Clean data and export final files."""
        print("\n" + "=" * 60)
        print("PHASE 3: CLEAN & EXPORT")
        print("=" * 60)
        
        # Filter bad rows
        clean = []
        removed = 0
        for row in self.all_data:
            title = row.get('title', '').strip()
            url = row.get('product_url', '').strip()
            price = row.get('product_current_price', '').strip()
            img = row.get('product_image_url', '').strip()
            
            if not title:
                removed += 1
                continue
            if not url:
                removed += 1
                continue
            if not price and not img:
                removed += 1
                continue
            
            clean.append(row)
        
        print(f"Removed: {removed}, Clean: {len(clean)}")
        
        # CSV export
        csv_path = os.path.join(OUTPUT_DIR, "cairosales_products.csv")
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for row in clean:
                writer.writerow({k: row.get(k, '') for k in COLUMNS})
        print(f"CSV: {csv_path} ({len(clean)} rows)")
        
        # JSON export
        json_path = os.path.join(OUTPUT_DIR, "cairosales_products.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        print(f"JSON: {json_path}")
        
        # Validation
        print(f"\n--- Validation ---")
        print(f"Columns: {len(COLUMNS)} (expected 18)")
        print(f"Header: {COLUMNS}")
        print(f"Rows: {len(clean)}")
        if clean:
            print(f"Sample row 1: {json.dumps(clean[0], ensure_ascii=False)[:200]}")
        
        return clean

async def main():
    scraper = CairoScraper()
    await scraper.start_browser()
    
    try:
        # Phase 1: Discover
        product_urls = await scraper.discover_all_categories_and_products()
        
        # Phase 2: Scrape
        if product_urls:
            await scraper.scrape_all_products()
            
            # Phase 3: Clean & Export
            clean_data = scraper.clean_and_export_final()
            
            print(f"\n{'='*60}")
            print(f"SCRAPING COMPLETE: {len(clean_data)} products")
            print(f"{'='*60}")
        else:
            print("No products found!")
    
    finally:
        await scraper.close_browser()

if __name__ == "__main__":
    asyncio.run(main())
