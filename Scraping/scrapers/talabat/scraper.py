import cloudscraper, re, json, csv, time, os, sys, math, random
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MAX_PRODUCTS = 2000000

TALABAT_COUNTRIES = [
    {'domain': 'www.talabat.com',  'path': 'egypt',   'label': 'Egypt',  'currency': 'EGP'},
]

OUTPUT_FILE = 'talabat_products.csv'
STATE_FILE = 'talabat_scraper_state.json'

SCRAPER = None

def get_scraper():
    global SCRAPER
    if SCRAPER is None:
        SCRAPER = cloudscraper.create_scraper()
    return SCRAPER

def fetch_json(url):
    s = get_scraper()
    for attempt in range(5):
        try:
            r = s.get(url, timeout=30)
            if r.status_code == 429:
                wait = 20 * (attempt + 1)
                print(f"  429 — waiting {wait}s (attempt {attempt+1}/5)...")
                time.sleep(wait)
                continue
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if m:
                return json.loads(m[1])
        except Exception:
            if attempt < 4:
                time.sleep(2)
    return None

def get_areas(country):
    url = f'https://{country["domain"]}/{country["path"]}/all-areas/groceries'
    data = fetch_json(url)
    if not data:
        return []
    areas_data = data['props']['pageProps']['areas']
    all_areas = []
    for city_id, sub_areas in areas_data.items():
        for sa in sub_areas:
            sa['country'] = country['label']
            all_areas.append(sa)
    return all_areas

def get_vendors(area, country):
    url = f'https://{country["domain"]}/{country["path"]}/groceries/{area["id"]}/{area["slug"]}?page=1'
    data = fetch_json(url)
    if not data:
        return []
    return data['props']['pageProps'].get('vendors', [])

def scrape_vendor(v, area_id, area_name, country, delay=0.3):
    branch_id = v.get('branchId')
    branch_slug = v.get('branchSlug')
    vendor_name = v.get('name', 'Unknown')
    if not branch_id or not branch_slug:
        return []

    try:
        domain = country['domain']
        path = country['path']
        url = f'https://{domain}/{path}/grocery/{branch_id}/{branch_slug}?aid={area_id}'
        data = fetch_json(url)
        if not data:
            return []

        pp = data['props']['pageProps']
        rows = []
        c = country

        if 'initialMenuState' in pp:
            ims = pp['initialMenuState']
            restaurant = ims.get('restaurant', {})
            market_name = restaurant.get('name') or restaurant.get('title') or vendor_name
            menu_data = ims.get('menuData', {})
            categories = menu_data.get('categories', [])
            for cat in categories:
                cat_name = cat.get('name', 'Unknown')
                items = cat.get('items', [])
                for p in items:
                    title = p.get('title') or p.get('name', '')
                    price = p.get('price', '')
                    discount_val = p.get('discount', 0) or p.get('discountPercentage', 0)
                    orig_price = p.get('originalPrice', price)
                    if discount_val and orig_price and orig_price != price:
                        discount_str = f"{c['currency']} {orig_price} (save {discount_val}%)"
                    elif discount_val:
                        discount_str = str(discount_val)
                    else:
                        discount_str = ''
                    full_url = f"https://{domain}/{path}/grocery/{branch_id}/{branch_slug}?aid={area_id}"
                    rows.append([title, price, discount_str, cat_name, full_url, market_name, area_name, c['label']])

        elif 'initialState' in pp:
            init_state = pp['initialState']
            store = init_state.get('groceryStore', {})
            market_name = store.get('name', vendor_name) if store else vendor_name
            categories = init_state.get('categories', [])
            for cat in categories:
                cat_name = cat['name']
                cat_slug = cat.get('slug', '')
                subs = cat.get('subCategories') or []
                if not subs and cat_slug:
                    subs = [{'slug': cat_slug, 'name': cat_name}]
                for sub in subs:
                    sub_slug = sub.get('slug', '')
                    sub_name = sub.get('name', cat_name)
                    if not sub_slug or not cat_slug:
                        continue
                    page = 1
                    while True:
                        prod_url = f'https://{domain}/{path}/grocery/{branch_id}/{branch_slug}/{cat_slug}/{sub_slug}?aid={area_id}&page={page}'
                        pd = fetch_json(prod_url)
                        if not pd:
                            break
                        try:
                            items_data = pd['props']['pageProps']['initialState'].get('itemsData', {})
                        except (KeyError, TypeError):
                            break
                        products = items_data.get('items', [])
                        if not products:
                            break
                        for p in products:
                            title = p.get('title', '')
                            price = p.get('price', '')
                            discount_val = p.get('discount', 0) or p.get('discountPercentage', 0)
                            orig_price = p.get('originalPrice', price)
                            if discount_val and orig_price and orig_price != price:
                                discount_str = f"{c['currency']} {orig_price} (save {discount_val}%)"
                            elif discount_val:
                                discount_str = str(discount_val)
                            else:
                                discount_str = ''
                            category_path = f"{cat_name} > {sub_name}"
                            full_url = f"https://{domain}/{path}/grocery/{branch_id}/{branch_slug}/{cat_slug}/{sub_slug}?aid={area_id}"
                            rows.append([title, price, discount_str, category_path, full_url, market_name, area_name, c['label']])
                        page_count = items_data.get('pageCount', 0)
                        current_page = items_data.get('currentPage', page)
                        if current_page >= page_count:
                            break
                        page += 1
                        time.sleep(delay + random.uniform(0, delay))
        return rows
    except Exception:
        return []

def init_state():
    state = {'total_products': 0, 'current_country_index': 0, 'current_area_index': 0, 'last_save_time': None}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            count = sum(1 for _ in f) - 1
        state['total_products'] = max(0, count)
        print(f"Existing CSV: {count:,} products — resuming in append mode")
    else:
        print("Fresh start — no existing data found")
    return state

def save_state(state):
    state['last_save_time'] = time.time()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)

def main():
    print("=" * 60)
    print("  Talabat Global Product Scraper v4")
    print(f"  Target: {MAX_PRODUCTS:,} products")
    print(f"  Country: {TALABAT_COUNTRIES[0]['label']}")
    print(f"  Type: Paginated (initialState — needs product page requests)")
    print("=" * 60)

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        print(f"Loaded state: {state['total_products']:,} products")
    else:
        state = init_state()

    if state['total_products'] == 0:
        with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['product_title', 'price', 'discount', 'category', 'url', 'market', 'area', 'country'])

    start_time = time.time()
    last_report = start_time

    try:
        max_workers = 2
        use_delay = 2.0
        use_cooldown = 3.0

        for ci in range(state.get('current_country_index', 0), len(TALABAT_COUNTRIES)):
            country = TALABAT_COUNTRIES[ci]

            print(f"\n{'='*60}")
            print(f"  Country: {country['label']} (paginated)")
            print(f"  Concurrency: {max_workers}, Delay: {use_delay}s, Cooldown: {use_cooldown}s")
            print(f"{'='*60}")

            areas = get_areas(country)
            if not areas:
                print(f"  No areas found — skipping")
                state['current_country_index'] = ci
                save_state(state)
                continue

            print(f"  Found {len(areas)} sub-areas")

            start_ai = state['current_area_index'] if ci == state.get('current_country_index', 0) else 0

            for ai in range(start_ai, len(areas)):
                area = areas[ai]
                area_id = area['id']
                area_slug = area['slug']
                area_name = area['name']
                city_name = area.get('cityName', '')
                display_name = f"{area_name}, {city_name}" if city_name else area_name

                print(f"\n[{ai+1}/{len(areas)}] {display_name} (ID: {area_id})")
                state['current_country_index'] = ci
                state['current_area_index'] = ai
                save_state(state)

                vendors = get_vendors(area, country)
                if not vendors:
                    print(f"  No vendors")
                    if ai < len(areas) - 1:
                        time.sleep(use_cooldown + random.uniform(0, 1))
                    continue

                print(f"  Vendors: {len(vendors)}")

                all_rows = []
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {pool.submit(scrape_vendor, v, area_id, area_name, country, use_delay): v for v in vendors}
                    for f in as_completed(futures):
                        rows = f.result()
                        all_rows.extend(rows)

                if all_rows:
                    with open(OUTPUT_FILE, 'a', encoding='utf-8', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerows(all_rows)
                    state['total_products'] += len(all_rows)

                now = time.time()
                elapsed = now - start_time
                rate = state['total_products'] / elapsed if elapsed > 0 else 0
                print(f"  +{len(all_rows)} products ({state['total_products']:,} total, {rate:.0f}/sec)")

                if state['total_products'] >= MAX_PRODUCTS:
                    print(f"\n{'='*60}")
                    print(f"  REACHED TARGET: {MAX_PRODUCTS:,} products!")
                    print(f"{'='*60}")
                    save_state(state)
                    return

                if ai < len(areas) - 1:
                    time.sleep(use_cooldown + random.uniform(0, 1))

                if ai % 5 == 0 or now - last_report > 60:
                    save_state(state)
                    last_report = now

            state['current_country_index'] = ci + 1
            state['current_area_index'] = 0
            save_state(state)

    except KeyboardInterrupt:
        print("\n\nInterrupted! Saving progress...")
    finally:
        save_state(state)

    elapsed = time.time() - start_time
    print(f"\nFinal count: {state['total_products']:,} products")
    print(f"Time: {elapsed/60:.1f} min, Rate: {state['total_products']/elapsed:.0f}/sec")

if __name__ == '__main__':
    main()
