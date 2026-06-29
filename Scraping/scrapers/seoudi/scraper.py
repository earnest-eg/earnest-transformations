import asyncio
import json
import os
import pandas as pd
import re
import zipfile
from playwright.async_api import async_playwright
from tqdm import tqdm
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Create Seoudi_Data directory if it doesn't exist
os.makedirs("Seoudi_Data", exist_ok=True)

BASE_URL = "https://seoudisupermarket.com"

async def load_all_products(page):
    """Scroll and click 'Load More' until all products are loaded."""
    print("  Loading all products...")
    previous_count = 0
    retries = 0
    while True:
        # Scroll to bottom
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)
        
        # Check product count
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        current_count = len(soup.find_all(class_=re.compile("ProductCard", re.I)))
        
        # Try clicking "Load More"
        load_more_btn = page.locator("button:has-text('Load More')")
        if await load_more_btn.count() > 0 and await load_more_btn.is_visible():
            try:
                await load_more_btn.click(timeout=5000)
                await asyncio.sleep(2)
            except:
                pass
        
        if current_count == previous_count:
            retries += 1
            if retries >= 3:
                break
        else:
            retries = 0
            
        previous_count = current_count
        print(f"    Current products loaded: {current_count}")
        
        if current_count >= 5000: # Safety break for extremely large categories
            break

def parse_products(html, category_name, category_url, selected_location):
    soup = BeautifulSoup(html, 'html.parser')
    products = []
    
    # Selector for product cards
    product_cards = soup.find_all(class_=re.compile("ProductCard", re.I))
    
    for card in product_cards:
        try:
            name_elem = card.find(class_=re.compile("ProductCard__Name", re.I))
            if not name_elem: continue
            product_name = name_elem.get_text(strip=True)
            
            link_elem = card.find('a', href=True)
            product_url = urljoin(BASE_URL, link_elem['href']) if link_elem else "N/A"
            
            brand = "N/A"
            
            # Price handling
            # The structure from research: <span class="font-bold">61.73 EGP</span>
            # Sometimes there's also a line-through price
            current_price = "N/A"
            old_price = "N/A"
            
            price_spans = card.find_all('span', class_=re.compile("font-bold|line-through", re.I))
            for span in price_spans:
                text = span.get_text(strip=True)
                if 'line-through' in str(span.get('class', [])):
                    old_price = text
                else:
                    current_price = text
            
            # Discount
            discount = "N/A"
            discount_elem = card.find(class_=re.compile("BadgeLabel--discount", re.I))
            if discount_elem:
                discount = discount_elem.get_text(strip=True)
            
            # Image
            img_elem = card.find('img', src=True)
            image_url = img_elem['src'] if img_elem else "N/A"
            
            # Availability
            out_of_stock = card.find(class_=re.compile("OutOfStock", re.I))
            availability = "Out of Stock" if out_of_stock else "In Stock"
            
            # Unit or weight
            weight_elem = card.find(class_=re.compile("ProductCard__Weight", re.I))
            unit_or_weight = weight_elem.get_text(strip=True) if weight_elem else "N/A"
            
            products.append({
                "product_name": product_name,
                "product_url": product_url,
                "category_name": category_name,
                "category_url": category_url,
                "brand": brand,
                "current_price": current_price,
                "old_price": old_price,
                "discount": discount,
                "image_url": image_url,
                "availability": availability,
                "unit_or_weight": unit_or_weight,
                "selected_location": selected_location
            })
        except Exception as e:
            continue
            
    return products

async def run():
    if not os.path.exists("Seoudi_Data/seoudi_state.json"):
        print("Error: seoudi_state.json not found. Run seoudi_find_best_location.py first.")
        return

    best_loc_file = "Seoudi_Data/best_location.json"
    if os.path.exists(best_loc_file):
        with open(best_loc_file, "r") as f:
            best_loc = json.load(f)
        selected_location = f"{best_loc['city']} - {best_loc['area']} - {best_loc['district']}"
    else:
        selected_location = "Unknown"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state="Seoudi_Data/seoudi_state.json")
        page = await context.new_page()
        
        print(f"Starting scraping with location: {selected_location}")
        await page.goto(BASE_URL + "/en", wait_until="networkidle")
        await asyncio.sleep(5)
        
        # Robust category discovery
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        excluded_keywords = ['account', 'cart', 'wishlist', 'tel:', 'contact', 'about', 'career', 'blog', 'policy', 'terms']
        
        potential_categories = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            name = a.get_text(strip=True)
            if not name or len(name) < 3: continue
            if any(k in href.lower() for k in excluded_keywords): continue
            if href.startswith('/en/') and href != '/en/':
                url = urljoin(BASE_URL, href)
                if url not in [c['url'] for c in potential_categories]:
                    # Heuristic: main categories are often short paths or in a specific list
                    potential_categories.append({'name': name, 'url': url})
        
        # Filter categories - we want things that look like actual product categories
        # I'll keep the ones that don't have too many dashes (products usually have many)
        # and are definitely under /en/
        categories = []
        for cat in potential_categories:
            path = cat['url'].replace(BASE_URL + "/en/", "")
            if path.count('-') < 4: # Typical category has few dashes, product has many
                categories.append(cat)
        
        print(f"Found {len(categories)} potential categories.")
        pd.DataFrame(categories).to_csv("Seoudi_Data/categories.csv", index=False)
        
        all_products = []
        seen_urls = set()
        
        for cat in tqdm(categories, desc="Scraping categories"):
            print(f"\nScraping category: {cat['name']} ({cat['url']})")
            try:
                await page.goto(cat['url'], wait_until="networkidle")
                await asyncio.sleep(2)
                
                # Check for subcategories
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                # Seoudi often has subcategories in a sidebar or as chips
                sub_links = []
                # Look for links that are children of the current category path
                cat_path = cat['url'].replace(BASE_URL, "")
                for a in soup.find_all('a', href=True):
                    if a['href'].startswith(cat_path + "/") and a['href'] != cat_path:
                        sub_links.append({'name': a.get_text(strip=True), 'url': urljoin(BASE_URL, a['href'])})
                
                # If no subcategories, just scrape this page
                if not sub_links:
                    await load_all_products(page)
                    html = await page.content()
                    prods = parse_products(html, cat['name'], cat['url'], selected_location)
                    for p in prods:
                        if p['product_url'] not in seen_urls:
                            all_products.append(p)
                            seen_urls.add(p['product_url'])
                    print(f"  Scraped {len(prods)} products.")
                else:
                    print(f"  Found {len(sub_links)} subcategories. Scraping them...")
                    for sub in sub_links:
                        if not sub['name']: continue
                        print(f"    Subcategory: {sub['name']}")
                        await page.goto(sub['url'], wait_until="networkidle")
                        await load_all_products(page)
                        html = await page.content()
                        prods = parse_products(html, f"{cat['name']} > {sub['name']}", sub['url'], selected_location)
                        for p in prods:
                            if p['product_url'] not in seen_urls:
                                all_products.append(p)
                                seen_urls.add(p['product_url'])
                        print(f"      Scraped {len(prods)} products.")
                        
            except Exception as e:
                print(f"Error scraping category {cat['name']}: {e}")
                
        # Final Deduplication
        df = pd.DataFrame(all_products)
        if not df.empty:
            df = df.drop_duplicates(subset=["product_url"])
            df = df.drop_duplicates(subset=["product_name", "category_name"])
            print(f"Total products after deduplication: {len(df)}")
            df.to_csv("Seoudi_Data/products.csv", index=False)
        else:
            print("No products found.")
            
        await browser.close()
        
    # Zip results
    print("Zipping results...")
    with zipfile.ZipFile("Seoudi_Data/Seoudi_Data.zip", "w") as z:
        if os.path.exists("Seoudi_Data/categories.csv"):
            z.write("Seoudi_Data/categories.csv", "categories.csv")
        if os.path.exists("Seoudi_Data/products.csv"):
            z.write("Seoudi_Data/products.csv", "products.csv")
    print("Done!")

if __name__ == "__main__":
    asyncio.run(run())
