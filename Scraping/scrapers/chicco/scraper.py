import httpx
from bs4 import BeautifulSoup
import pandas as pd
import asyncio
import logging
from datetime import datetime
import pytz
import re
import os
import json
import zipfile

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TIMEZONE = "Africa/Cairo"
cairo_tz = pytz.timezone(TIMEZONE)

CONCURRENCY_LIMIT = 5 # Respectful concurrency

async def parse_product(client, url, semaphore):
    async with semaphore:
        logger.info(f"Scraping product: {url}")
        try:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            
            # 1. title
            title_tag = soup.find("h1", class_="product_title")
            title = title_tag.text.strip() if title_tag else ""
            
            # If title is too generic (starts with "Product "), try to get it from URL slug
            if title.lower().startswith("product ") or not title:
                slug = url.rstrip("/").split("/")[-1]
                # Convert slug like 'chicco-fit360-mirror-car-seat' to 'Chicco Fit360 Mirror Car Seat'
                # Remove the hash-like suffix if present (e.g., -ymrn-8107)
                clean_slug = re.sub(r'-[a-z]{4}-\d{4}$', '', slug)
                title = clean_slug.replace("-", " ").title()
            
            # 2. name (simplified title)
            name = title.split("-")[0].strip() if "-" in title else title
            
            # 3 & 4. Prices
            price_box = soup.find("p", class_="price")
            current_price = ""
            old_price = ""
            
            if price_box:
                ins_tag = price_box.find("ins")
                del_tag = price_box.find("del")
                
                if ins_tag and del_tag:
                    current_price = re.sub(r'[^\d.]', '', ins_tag.text)
                    old_price = re.sub(r'[^\d.]', '', del_tag.text)
                else:
                    # Single price
                    price_text = price_box.get_text()
                    # If multiple prices (range), pick the first one
                    prices = re.findall(r'[\d,.]+', price_text.replace(",", ""))
                    if prices:
                        current_price = prices[0]
            
            # 5. product_discount
            discount = ""
            try:
                if current_price and old_price:
                    cp = float(current_price)
                    op = float(old_price)
                    if op > cp:
                        discount = f"{((op - cp) / op) * 100:.3f}%"
            except:
                pass
            
            # 6. product_url
            product_url = url
            
            # 7. product_image_url
            img_tag = soup.select_one(".woocommerce-product-gallery__image img, .wp-post-image")
            image_url = img_tag.get("src") if img_tag else ""
            
            # 8. product_seller
            product_seller = "Chicco Egypt"
            
            # 9. product_availability
            avail_tag = soup.find("p", class_="stock")
            availability = "in_stock"
            if avail_tag and ("out-of-stock" in avail_tag.get("class", []) or "Out of stock" in avail_tag.text):
                availability = "out_of_stock"
            elif avail_tag and "In stock" not in avail_tag.text:
                availability = "out_of_stock"
                
            # 10 & 11. Categories
            category = ""
            subcategory = ""
            breadcrumb = soup.select(".woocommerce-breadcrumb a")
            
            category_map = {
                'مُكَمِّلات': 'baby products > accessories',
                'اللهايات والتهدئة': 'baby products > soothing',
                'ساحات اللعب': 'baby products > playards',
                'مقاعد السيارات': 'baby products > car seats',
                'الإطعام والتهدئة': 'baby products > feeding',
                'تغذية الأطفال الصغار': 'baby products > feeding',
                'كراسي الطعام المرتفعة ومقاعد الرفع': 'baby products > high chairs',
                'مهود الأطفال': 'baby products > nursery',
                'أنظمة السفر – مجموعات مقاعد السيارات وعربات الأطفال': 'baby products > travel systems',
                'حمالات الأطفال وأنشطة اللعب': 'baby products > carriers',
                'عربات الأطفال': 'baby products > strollers',
                'التدريب على استخدام المرحاض': 'baby products > toilet training'
            }

            if len(breadcrumb) > 1:
                raw_cats = [a.text.strip() for a in breadcrumb[1:]]
                if len(raw_cats) >= 1:
                    raw_cat = raw_cats[0]
                    category = category_map.get(raw_cat, raw_cat)
                if len(raw_cats) >= 2:
                    subcategory = raw_cats[1]
            
            # 12 & 13. Unit & Weight
            unit = ""
            weight = ""
            # Check Additional Information table
            info_table = soup.find("table", class_="woocommerce-product-attributes")
            if info_table:
                rows = info_table.find_all("tr")
                for row in rows:
                    label = row.find("th").text.strip().lower()
                    value = row.find("td").text.strip()
                    if "weight" in label:
                        weight = value
                    if "size" in label or "pack" in label:
                        unit = value
            
            # 14 & 15. Time
            scraping_time = datetime.now(cairo_tz).strftime("%Y-%m-%d %H:%M:%S")
            timestamp_timezone = TIMEZONE
            
            # 16. product_brand
            product_brand = "Chicco" # Default for this site
            
            # 17 & 18. RAM/Storage (Placeholders)
            product_ram = ""
            product_storage = ""
            
            return {
                "title": title,
                "name": name,
                "product_current_price": current_price,
                "product_old_price": old_price,
                "product_discount": discount,
                "product_url": product_url,
                "product_image_url": image_url,
                "product_seller": product_seller,
                "product_availability": availability,
                "product_category": category,
                "product_subcategory": subcategory,
                "product_unit": unit,
                "product_weight": weight,
                "scraping_time": scraping_time,
                "timestamp_timezone": timestamp_timezone,
                "product_brand": product_brand,
                "product_ram": product_ram,
                "product_storage": product_storage
            }
            
        except Exception as e:
            logger.error(f"Error parsing {url}: {e}")
            return None

async def main():
    if not os.path.exists("todo_products.csv"):
        logger.error("todo_products.csv not found. Run discovery.py first.")
        return

    df_todo = pd.read_csv("todo_products.csv")
    urls = df_todo["product_url"].tolist()
    
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        tasks = [parse_product(client, url, semaphore) for url in urls]
        results = await asyncio.gather(*tasks)
    
    # Filter out None results
    clean_results = [r for r in results if r is not None]
    
    # Create DataFrame
    df = pd.DataFrame(clean_results)
    
    # Ensure all 18 columns exist in correct order
    cols = [
        "title", "name", "product_current_price", "product_old_price", "product_discount",
        "product_url", "product_image_url", "product_seller", "product_availability",
        "product_category", "product_subcategory", "product_unit", "product_weight",
        "scraping_time", "timestamp_timezone", "product_brand", "product_ram", "product_storage"
    ]
    df = df[cols]
    
    # Save CSV
    df.to_csv("chicco_products.csv", index=False)
    logger.info(f"Saved {len(df)} products to chicco_products.csv")
    
    # Save JSON
    with open("chicco_products.json", "w", encoding="utf-8") as f:
        json.dump(clean_results, f, ensure_ascii=False, indent=2)
    logger.info("Saved products to chicco_products.json")
    
    # Archive
    with zipfile.ZipFile("chicco_data_export.zip", "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.write("chicco_products.csv")
        zipf.write("chicco_products.json")
    logger.info("Created chicco_data_export.zip")

if __name__ == "__main__":
    asyncio.run(main())
