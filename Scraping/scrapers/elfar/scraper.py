import urllib.request
import urllib.error
import json
import csv
import re
import time
import sys
import os
from datetime import datetime, timezone

BASE = 'https://api.mahmoudelfar.com/api'
PRODUCT_URL_BASE = 'https://mahmoudelfar.com/en/products/'
TIMEZONE = 'Africa/Cairo'

def fetch_json(url, timeout=60, retries=3):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise e

def clean_price(price_str):
    if not price_str:
        return None
    cleaned = re.sub(r'[^\d.,]', '', str(price_str))
    cleaned = cleaned.replace(',', '')
    try:
        return round(float(cleaned), 2)
    except:
        return None

def extract_brand(name, slug):
    if not name:
        return ''
    name_lower = name.lower()
    known_brands = {
        'jimmy': 'Jimmy', 'san benedetto': 'San Benedetto', 'twix': 'Twix',
        'costa': 'Costa Coffee', 'nestle': 'Nestlé', 'pepsi': 'Pepsi',
        'coca-cola': 'Coca-Cola', 'coca cola': 'Coca-Cola', 'fanta': 'Fanta',
        'sprite': 'Sprite', 'barbican': 'Barbican', 'juhayna': 'Juhayna',
        'milkys': 'Milkys', 'kiri': 'Kiri', 'pascual': 'Pascual',
        'laktonia': 'Laktonia', 'beak': 'Beak', 'capo': 'Capo',
        'kraft': 'Kraft', 'nido': 'Nido', 'cerelac': 'Cerelac',
        'gerber': 'Gerber', 'pampers': 'Pampers', 'huggies': 'Huggies',
        'head & shoulders': 'Head & Shoulders', 'pantene': 'Pantene',
        'dove': 'Dove', 'lux': 'Lux', 'fa': 'Fa', 'nivea': 'Nivea',
        'colgate': 'Colgate', 'signal': 'Signal', 'closeup': 'Closeup',
        'sensodyne': 'Sensodyne', 'oral-b': 'Oral-B', 'oral b': 'Oral-B',
        'persil': 'Persil', 'ariel': 'Ariel', 'tide': 'Tide',
        'omo': 'Omo', 'bonux': 'Bonux', 'comet': 'Comet',
        'clorox': 'Clorox', 'jif': 'Jif', 'cif': 'Cif',
        'pride': 'Pride', 'vim': 'Vim', 'fairy': 'Fairy',
        'febreze': 'Febreze', 'dettol': 'Dettol', 'lysol': 'Lysol',
        'pedigree': 'Pedigree', 'whiskas': 'Whiskas', 'friskies': 'Friskies',
        'appetite': 'Appetite', 'appetina': 'Appetina',
        'molto': 'Molto', 'pronto': 'Pronto', 'cadbury': 'Cadbury',
        'samsung': 'Samsung', 'lg': 'LG', 'philips': 'Philips',
    }
    for key, brand in known_brands.items():
        if key in name_lower:
            return brand
    if slug:
        slug_lower = slug.lower()
        for key, brand in known_brands.items():
            if key in slug_lower:
                return brand
    return ''

def extract_ram_storage(name):
    ram = ''
    storage = ''
    if not name:
        return ram, storage
    
    ram_patterns = [
        (r'(\d+)\s*GB\s*(?:RAM|ram)', 'ram'),
        (r'(?:RAM|ram)\s*(\d+)\s*GB', 'ram'),
        (r'(\d+)\s*[Gg][Bb]\s+[Rr][Aa][Mm]', 'ram'),
    ]
    for pat in ram_patterns:
        m = re.search(pat[0], name)
        if m:
            ram = m.group(1) + 'GB'
            break
    
    storage_patterns = [
        (r'(\d+)\s*(?:GB|TB)\s*(?:SSD|HDD|Storage)', 'storage'),
        (r'(\d+)\s*(?:GB|TB)\s+(?:SSD|HDD)', 'storage'),
        (r'(\d+)\s*[Gg][Bb]\s+(?:ストレージ|存储|储存)', 'storage'),
    ]
    for pat in storage_patterns:
        m = re.search(pat[0], name)
        if m:
            storage = m.group(1) + ('TB' if 'TB' in m.group(0) else 'GB')
            break
    
    if not storage:
        m = re.search(r'(\d+)\s*(?:GB|TB)\s*(?:SSD|HDD)', name, re.IGNORECASE)
        if m:
            storage = m.group(1) + ('TB' if 'TB' in m.group(0) else 'GB') + ' ' + ('SSD' if 'SSD' in name.upper() else 'HDD' if 'HDD' in name.upper() else '')
    
    return ram, storage

def extract_unit_weight(name, weight):
    unit_map = {
        'piece': 'pcs', 'pieces': 'pcs', 'pack': 'pcs',
        'kg': 'KG', 'gm': 'g', 'g': 'g', 'ml': 'ml', 'l': 'L',
    }
    unit = ''
    weight_clean = ''
    
    if weight:
        weight_clean = weight.strip()
        parts = weight.split()
        if len(parts) >= 2:
            qty = parts[0]
            wunit = parts[1].lower()
            for key, val in unit_map.items():
                if wunit == key:
                    unit = qty + ' ' + val
                    break
    
    if not unit and name:
        m = re.search(r'(\d+)\s*(pieces|pcs|pack|gm|g|kg|ml|l|L)\b', name, re.IGNORECASE)
        if m:
            qty = m.group(1)
            wunit = m.group(2).lower()
            normalized = unit_map.get(wunit, wunit)
            unit = qty + ' ' + normalized
    
    return unit, weight_clean

def get_category_hierarchy(cat_id, cat_map):
    hierarchy = cat_map.get(str(cat_id), {})
    name = hierarchy.get('name', '')
    parent = hierarchy.get('parent_name', '')
    grandparent = hierarchy.get('grandparent_name', '')
    
    path_parts = [p for p in [grandparent, parent, name] if p]
    path = ' > '.join(path_parts) if path_parts else ''
    main_cat = grandparent or parent or name
    subcat = ''
    if name and (parent or grandparent):
        subcat = name
    elif path_parts:
        subcat = path_parts[-1]
    
    return path, main_cat, subcat

def standardize_category(main_cat, subcat):
    cat_rules = {
        'fruits': ('grocery > fruits & vegetables', 'Fresh Fruits'),
        'vegetables': ('grocery > fruits & vegetables', 'Fresh Vegetables'),
        'herbs': ('grocery > fruits & vegetables', 'Fresh Herbs'),
        'deli': ('grocery > deli', 'Deli'),
        'fresh cheese': ('grocery > deli', 'Fresh Cheese'),
        'branded cheese': ('grocery > deli', 'Branded Cheese'),
        'fresh cold cuts': ('grocery > deli', 'Cold Cuts'),
        'bakery': ('grocery > bakery', 'Bakery'),
        'pastry': ('grocery > bakery', 'Pastry'),
        'pizza': ('grocery > bakery', 'Pizza'),
        'croissants': ('grocery > bakery', 'Croissants'),
        'baguette': ('grocery > bakery', 'Baguette'),
        'bread': ('grocery > bakery', 'Bread'),
        'dairy': ('grocery > dairy', 'Dairy'),
        'eggs': ('grocery > dairy', 'Eggs'),
        'butter': ('grocery > dairy', 'Butter & Creams'),
        'milk': ('grocery > dairy', 'Milk'),
        'yogurt': ('grocery > dairy', 'Yogurt'),
        'cheese': ('grocery > dairy', 'Cheese'),
        'cream': ('grocery > dairy', 'Cream'),
        'meat': ('grocery > meat & poultry', 'Meat'),
        'poultry': ('grocery > meat & poultry', 'Poultry'),
        'seafood': ('grocery > meat & poultry', 'Seafood'),
        'chicken': ('grocery > meat & poultry', 'Chicken'),
        'beverages': ('grocery > beverages', 'Beverages'),
        'water': ('grocery > beverages', 'Water'),
        'tea': ('grocery > beverages', 'Tea'),
        'coffee': ('grocery > beverages', 'Coffee'),
        'soft drinks': ('grocery > beverages', 'Soft Drinks'),
        'juice': ('grocery > beverages', 'Juice'),
        'food cupboard': ('grocery > pantry', 'Food Cupboard'),
        'rice': ('grocery > pantry', 'Rice'),
        'pasta': ('grocery > pantry', 'Pasta'),
        'oil': ('grocery > pantry', 'Oil & Ghee'),
        'sauces': ('grocery > pantry', 'Sauces & Dressings'),
        'canned': ('grocery > pantry', 'Canned Food'),
        'snacks': ('grocery > snacks', 'Snacks'),
        'chips': ('grocery > snacks', 'Chips'),
        'nuts': ('grocery > snacks', 'Nuts & Seeds'),
        'chocolates': ('grocery > chocolates & sweets', 'Chocolates'),
        'biscuits': ('grocery > chocolates & sweets', 'Biscuits & Cookies'),
        'candies': ('grocery > chocolates & sweets', 'Candies'),
        'frozen': ('grocery > frozen', 'Frozen'),
        'ice cream': ('grocery > frozen', 'Ice Cream'),
        'frozen vegetables': ('grocery > frozen', 'Frozen Vegetables'),
        'frozen meat': ('grocery > frozen', 'Frozen Meat'),
        'ready to cook': ('grocery > frozen', 'Ready to Cook'),
        'cleaning': ('home > cleaning', 'Cleaning'),
        'household': ('home > cleaning', 'Household'),
        'laundry': ('home > cleaning', 'Laundry Detergents'),
        'cleaners': ('home > cleaning', 'Multi-Purpose Cleaners'),
        'personal care': ('personal care > general', 'Personal Care'),
        'oral care': ('personal care > oral care', 'Oral Care'),
        'feminine care': ('personal care > feminine care', 'Feminine Care'),
        'shampoo': ('personal care > hair care', 'Shampoo'),
        'conditioner': ('personal care > hair care', 'Conditioner'),
        'hair dye': ('personal care > hair care', 'Hair Dye'),
        'body care': ('personal care > body care', 'Body Care'),
        'skin care': ('personal care > skin care', 'Skin Care'),
        'baby': ('baby products', 'Baby Products'),
        'diapers': ('baby products', 'Diapers'),
        'baby food': ('baby products', 'Baby Food'),
        'baby care': ('baby products', 'Baby Care'),
        'pet': ('pet supplies', 'Pet Care'),
        'dog': ('pet supplies', 'Dog Supplies'),
        'cat': ('pet supplies', 'Cat Supplies'),
        'home & kitchen': ('home > kitchen', 'Home & Kitchen'),
        'kitchen': ('home > kitchen', 'Kitchen'),
        'cookware': ('home > kitchen', 'Cookware'),
        'home appliances': ('electronics > appliances', 'Home Appliances'),
        'kettles': ('electronics > appliances', 'Kettles'),
        'mixers': ('electronics > appliances', 'Mixers & Grinders'),
        'pharmacy': ('pharmacy > medicines', 'Pharmacy'),
        'medical': ('pharmacy > medicines', 'Medical Supplies'),
        'stationery': ('stationery & books', 'Stationery'),
        'books': ('stationery & books', 'Books'),
        'toys': ('toys & games', 'Toys'),
        'games': ('toys & games', 'Games'),
        'lifestyle': ('lifestyle', 'Lifestyle'),
        'international cuisine': ('grocery > international', 'International Cuisine'),
        'bulk': ('grocery > bulk', 'Bulk & Save'),
    }
    
    for key, (cat, sub) in cat_rules.items():
        if key in main_cat.lower() or key in subcat.lower():
            return cat, sub
    
    return main_cat, subcat

def scrape_all_products():
    scraping_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    # Get all categories first
    print("Fetching categories...")
    cats_data = fetch_json(f'{BASE}/categories')
    
    # Build category map
    cat_map = {}
    def build_cat_map(cats_list, parent_name='', grandparent_name=''):
        for c in cats_list:
            cid = str(c['id'])
            cat_map[cid] = {
                'name': c.get('name', ''),
                'slug': c.get('slug', ''),
                'parent_name': parent_name,
                'grandparent_name': grandparent_name,
            }
            children = c.get('children', [])
            if children:
                build_cat_map(children, c.get('name', ''), parent_name if not parent_name else parent_name)
    
    build_cat_map(cats_data.get('data', []))
    print(f"Loaded {len(cat_map)} categories")
    
    # Scrape all products via pagination with max limit
    all_products = []
    limit = 5000
    page = 1
    
    while True:
        url = f'{BASE}/products?page={page}&limit={limit}'
        print(f"Fetching page {page}...")
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"Error on page {page}: {e}")
            break
        
        products = data.get('data', [])
        if not products:
            break
        
        all_products.extend(products)
        meta = data.get('meta', {})
        total = meta.get('total', 0)
        last_page = meta.get('last_page', 0)
        
        print(f"  Got {len(products)} products (total collected: {len(all_products)}/{total})")
        
        if page >= last_page:
            break
        page += 1
        time.sleep(0.5)
    
    print(f"\nTotal products collected: {len(all_products)}")
    return all_products, cat_map, scraping_time

def process_products(all_products, cat_map, scraping_time):
    rows = []
    total = len(all_products)
    
    for idx, p in enumerate(all_products):
        if idx % 100 == 0:
            print(f"Processing {idx}/{total}...")
        
        name = p.get('name', '') or ''
        slug = p.get('slug', '') or ''
        
        title = name
        
        product_url = PRODUCT_URL_BASE + slug
        
        image_data = p.get('base_image', {}) or {}
        product_image_url = image_data.get('original_image_url', '') or image_data.get('large_image_url', '') or \
                           image_data.get('medium_image_url', '') or image_data.get('small_image_url', '') or ''
        
        current_price = clean_price(p.get('final_pr', ''))
        old_price = clean_price(p.get('original_pr', ''))
        
        discount = ''
        if old_price and current_price and old_price > current_price:
            discount = round(((old_price - current_price) / old_price) * 100, 2)
            discount = str(discount) + '%'
        elif old_price and current_price and old_price == current_price:
            discount = ''
        else:
            discount = ''
        
        in_stock = p.get('in_stock', False)
        if in_stock is True:
            availability = 'in_stock'
        elif in_stock is False:
            availability = 'out_of_stock'
        else:
            availability = ''
        
        weight = p.get('weight', '') or ''
        unit, weight_clean = extract_unit_weight(name, weight)
        
        brand = extract_brand(name, slug)
        ram, storage = extract_ram_storage(name)
        
        # Category info from the product's own parent (category)
        parent_id = str(p.get('parent_id', '')) if p.get('parent_id') else ''
        category_path = ''
        main_cat = ''
        subcat = ''
        
        if parent_id and parent_id in cat_map:
            ch = cat_map[parent_id]
            parent_name = ch.get('parent_name', '')
            grandparent_name = ch.get('grandparent_name', '')
            cat_name = ch.get('name', '')
            
            parts = [gp for gp in [grandparent_name, parent_name, cat_name] if gp]
            category_path = ' > '.join(parts) if parts else ''
            main_cat = grandparent_name or parent_name or cat_name
            subcat = (cat_name if cat_name != main_cat else parent_name if parent_name and parent_name != grandparent_name else '')
        
        if not category_path:
            category_path = ' > '.join(p for p in [cat_map.get(parent_id, {}).get('grandparent_name', ''), 
                                                      cat_map.get(parent_id, {}).get('parent_name', ''),
                                                      cat_map.get(parent_id, {}).get('name', '')] if p)
        
        scat, ssub = standardize_category(main_cat or category_path, subcat)
        if scat:
            category_path_std = scat
            product_category = scat
            product_subcategory = ssub
        else:
            product_category = category_path
            product_subcategory = subcat
        
        row = {
            'title': title,
            'name': name,
            'product_current_price': current_price,
            'product_old_price': old_price if old_price else '',
            'product_discount': discount,
            'product_url': product_url,
            'product_image_url': product_image_url,
            'product_seller': 'Mahmoud El Far Market',
            'product_availability': availability,
            'product_category': product_category,
            'product_subcategory': product_subcategory,
            'product_unit': unit,
            'product_weight': weight_clean,
            'scraping_time': scraping_time,
            'timestamp_timezone': TIMEZONE,
            'product_brand': brand,
            'product_ram': ram,
            'product_storage': storage,
        }
        rows.append(row)
    
    return rows

def save_csv(rows, filepath):
    fieldnames = [
        'title', 'name', 'product_current_price', 'product_old_price',
        'product_discount', 'product_url', 'product_image_url', 'product_seller',
        'product_availability', 'product_category', 'product_subcategory',
        'product_unit', 'product_weight', 'scraping_time', 'timestamp_timezone',
        'product_brand', 'product_ram', 'product_storage'
    ]
    
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    
    print(f"Saved {len(rows)} rows to {filepath}")
    return filepath

def validate_csv(filepath):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        expected = [
            'title', 'name', 'product_current_price', 'product_old_price',
            'product_discount', 'product_url', 'product_image_url', 'product_seller',
            'product_availability', 'product_category', 'product_subcategory',
            'product_unit', 'product_weight', 'scraping_time', 'timestamp_timezone',
            'product_brand', 'product_ram', 'product_storage'
        ]
        
        print(f"\n=== Validation ===")
        print(f"Expected columns: {len(expected)}")
        print(f"Actual columns: {len(fieldnames)}")
        
        if fieldnames == expected:
            print("✓ Column names match exactly")
        else:
            print("✗ Column MISMATCH:")
            for i, (e, a) in enumerate(zip(expected, fieldnames or [])):
                if e != a:
                    print(f"  Position {i}: expected '{e}' got '{a}'")
        
        row_count = 0
        for row in reader:
            row_count += 1
            if row_count == 1:
                sample = row
        
        print(f"Total rows: {row_count}")
        
        # Check for missing/invalid data
        rows_with_errors = 0
        for row in reader:
            if not row.get('title') or not row.get('product_url'):
                rows_with_errors += 1
        
        print(f"Rows with missing title/url: {rows_with_errors}")

def main():
    print("=" * 60)
    print("Mahmoud El Far Market - Product Scraper")
    print("=" * 60)
    
    products, cat_map, scraping_time = scrape_all_products()
    
    print(f"\nProcessing {len(products)} products...")
    rows = process_products(products, cat_map, scraping_time)
    
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mahmoud_elfar_products.csv')
    save_csv(rows, csv_path)
    
    validate_csv(csv_path)
    
    print(f"\n✓ Scraping complete!")
    print(f"  Total products: {len(rows)}")
    print(f"  Output: {csv_path}")

if __name__ == '__main__':
    main()
