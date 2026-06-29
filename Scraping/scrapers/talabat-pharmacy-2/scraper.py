import asyncio
import pandas as pd
import json
from playwright.async_api import async_playwright
import datetime
import os

# Configuration
TARGET_AREA_URL = "https://www.talabat.com/egypt/pharmacies/8042/zamalek-el-ahly-club"
FINAL_FILE = "talabat_pharmacies_products.csv"

def find_key_recursive(obj, key):
    """Deep search for a key in a nested dict/list."""
    if isinstance(obj, dict):
        if key in obj: return obj[key]
        for v in obj.values():
            res = find_key_recursive(v, key)
            if res: return res
    elif isinstance(obj, list):
        for v in obj:
            res = find_key_recursive(v, key)
            if res: return res
    return None

async def extract_from_json(page, pharm_name, pharm_url):
    """Extracts products from __NEXT_DATA__."""
    products = []
    try:
        data = await page.evaluate("() => typeof __NEXT_DATA__ !== 'undefined' ? __NEXT_DATA__ : null")
        if not data: return []
        
        # Search for categories which contain items
        categories = find_key_recursive(data, 'categories')
        if not categories or not isinstance(categories, list):
            # Try searching for 'items' directly in a menu-like structure
            menu = find_key_recursive(data, 'menu')
            categories = menu.get('categories', []) if menu else []

        if categories:
            for cat in categories:
                if not isinstance(cat, dict): continue
                cat_name = cat.get('name', 'General')
                items = cat.get('items', [])
                for item in items:
                    products.append({
                        "title": item.get('name', ''),
                        "current_price": item.get('price', ''),
                        "old_price": item.get('oldPrice', ''),
                        "discount": item.get('discountText', ''),
                        "url": pharm_url,
                        "category": cat_name,
                        "name": pharm_name,
                        "Specifications": item.get('description', 'Check site'),
                        "img_URL": item.get('image', ''),
                        "time_and_place": f"{datetime.datetime.now()} - {pharm_name}, Zamalek"
                    })
    except Exception as e:
        print(f"Extraction error for {pharm_name}: {e}")
    return products

async def scrape_talabat():
    async with async_playwright() as p:
        print(f"[{datetime.datetime.now()}] Launching Browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Step 1: Load Area Page to get pharmacy list
        print(f"[{datetime.datetime.now()}] Loading Area Page...")
        await page.goto(TARGET_AREA_URL, wait_until="domcontentloaded")
        await asyncio.sleep(10)
        
        # Get links from JSON
        data = await page.evaluate("() => typeof __NEXT_DATA__ !== 'undefined' ? __NEXT_DATA__ : null")
        vendors = find_key_recursive(data, 'vendors') if data else []
        
        if not vendors:
            print("Failed to find pharmacies in JSON.")
            await browser.close()
            return

        pharmacies = []
        for v in vendors:
            name = v.get('name')
            # Use branchId or restaurantId as the unique marker
            vid = v.get('branchId') or v.get('restaurantId') or v.get('id')
            url_part = v.get('menuUrl') or v.get('branchUrl')
            if name and vid:
                pharmacies.append({
                    'name': name,
                    'id': str(vid),
                    'full_url': f"https://www.talabat.com{url_part}" if url_part and url_part.startswith('/') else url_part
                })

        print(f"Total Pharmacies to process: {len(pharmacies)}")
        
        all_products = []
        
        for i, pharm in enumerate(pharmacies):
            print(f"[{i+1}/{len(pharmacies)}] Processing: {pharm['name']} (ID: {pharm['id']})")
            
            try:
                await page.goto(TARGET_AREA_URL, wait_until="domcontentloaded")
                await asyncio.sleep(7)
                
                # Click the pharmacy link using the ID in the href
                selector = f"a[href*='{pharm['id']}']"
                exists = await page.query_selector(selector)
                
                if exists:
                    # Scroll to element to ensure it's clickable
                    await page.evaluate(f"document.querySelector(\"{selector}\").scrollIntoView()")
                    await asyncio.sleep(1)
                    await page.evaluate(f"() => document.querySelector(\"{selector}\").click()")
                    await asyncio.sleep(15) 
                    
                    if "talabat.com/egypt" in page.url and len(page.url.split('/')) <= 5:
                        print(f"Blocked for {pharm['name']}. Skipping.")
                        continue
                        
                    # Scroll to load (helps populate JSON in some cases)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                    await asyncio.sleep(1)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)

                    # Extract
                    products = await extract_from_json(page, pharm['name'], page.url)
                    
                    # Fallback to DOM if JSON was thin
                    if len(products) < 5:
                        print("JSON extraction yielded few results. Falling back to DOM...")
                        dom_items = await page.evaluate("""() => {
                            const res = [];
                            document.querySelectorAll('div[data-testid="product"]').forEach(card => {
                                res.push({
                                    title: card.querySelector('h6, .h6')?.innerText || "",
                                    current_price: card.querySelector('[class*="currentPrice"], .price')?.innerText || "",
                                    old_price: card.querySelector('[class*="oldPrice"], .old-price')?.innerText || "",
                                    discount: card.querySelector('[class*="discount"], .discount')?.innerText || "",
                                    img_url: card.querySelector('img')?.src || ""
                                });
                            });
                            return res;
                        }""")
                        for item in dom_items:
                            products.append({
                                "title": item['title'], "current_price": item['current_price'], "old_price": item['old_price'],
                                "discount": item['discount'], "url": page.url, "category": "General",
                                "name": pharm['name'], "Specifications": "See site", "img_URL": item['img_url'],
                                "time_and_place": f"{datetime.datetime.now()} - {pharm['name']}, Zamalek"
                            })
                    
                    all_products.extend(products)
                    print(f"Collected {len(products)} products. Total: {len(all_products)}")
                    
                    # Intermediate save
                    if len(all_products) > 0:
                        pd.DataFrame(all_products).to_csv(f"talabat_progress.csv", index=False, encoding='utf-8-sig')
                else:
                    print(f"Link for {pharm['name']} not found on page.")
                    
            except Exception as e:
                print(f"Error processing {pharm['name']}: {e}")

        # Final Save
        df = pd.DataFrame(all_products)
        df.to_csv(FINAL_FILE, index=False, encoding='utf-8-sig')
        print(f"SUCCESS! Total products collected: {len(all_products)}")
        print(f"Data saved to {FINAL_FILE}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_talabat())
