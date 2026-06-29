import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import time
from datetime import datetime
import json

def get_soup(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def scrape_product(url):
    soup = get_soup(url)
    if not soup:
        return None
    
    data = {}
    data['product_url'] = url
    
    # Title
    title_tag = soup.find('h1', class_='product_title') or soup.find('h1')
    if title_tag:
        data['title'] = title_tag.text.strip()
    else:
        # Fallback to h2 elementor headings or og:title
        h2_headings = soup.find_all('h2', class_='elementor-heading-title')
        if h2_headings:
            # Usually the product title is one of the first few meaningful ones
            # But let's try og:title first as it's more reliable for the product name
            og_title = soup.find('meta', property='og:title')
            if og_title:
                data['title'] = og_title['content'].split(' - ')[0].strip()
            else:
                data['title'] = h2_headings[0].text.strip()
        else:
            og_title = soup.find('meta', property='og:title')
            data['title'] = og_title['content'].split(' - ')[0].strip() if og_title else ''
    
    # Prices
    price_container = soup.find('p', class_='price') or soup.find('div', class_='jet-woo-product-price')
    if price_container:
        ins = price_container.find('ins')
        del_tag = price_container.find('del')
        
        if ins:
            data['product_current_price'] = ins.text.strip()
            data['product_old_price'] = del_tag.text.strip() if del_tag else ''
        else:
            # Single price or range
            data['product_current_price'] = price_container.text.strip()
            data['product_old_price'] = ''
    else:
        data['product_current_price'] = ''
        data['product_old_price'] = ''
        
    # Image
    img_tag = soup.find('div', class_='woocommerce-product-gallery__image') or soup.find('img', class_='wp-post-image')
    if img_tag:
        if img_tag.name == 'div':
            img = img_tag.find('img')
            data['product_image_url'] = img['src'] if img else ''
        else:
            data['product_image_url'] = img_tag['src']
    
    if not data.get('product_image_url'):
        og_img = soup.find('meta', property='og:image')
        data['product_image_url'] = og_img['content'] if og_img else ''
        
    # Availability
    stock_tag = soup.find('p', class_='stock')
    data['product_availability'] = stock_tag.text.strip() if stock_tag else 'in_stock'
    
    # Categories
    meta_container = soup.find('div', class_='product_meta')
    if meta_container:
        cat_tags = meta_container.find_all('span', class_='posted_in')
        cats = [a.text.strip() for tag in cat_tags for a in tag.find_all('a')]
        data['product_category'] = ' > '.join(cats) if cats else ''
    else:
        data['product_category'] = ''
        
    # Specs (for brand, ram, storage, weight, unit)
    specs = {}
    spec_table = soup.find('table', class_='woocommerce-product-attributes')
    if spec_table:
        for row in spec_table.find_all('tr'):
            label = row.find('th').text.strip()
            value = row.find('td').text.strip()
            specs[label] = value
            
    data['specs'] = json.dumps(specs)
    
    # Static fields
    data['product_seller'] = 'Unionaire'
    data['product_brand'] = 'Unionaire'
    data['scraping_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data['timestamp_timezone'] = 'Africa/Cairo'
    
    return data

def main():
    if not os.path.exists('data/todo_products.csv'):
        print("todo_products.csv not found.")
        return
        
    df_todo = pd.read_csv('data/todo_products.csv')
    
    raw_file = 'data/raw_products.csv'
    if os.path.exists(raw_file):
        df_raw = pd.read_csv(raw_file)
        scraped_urls = set(df_raw['product_url'].tolist())
    else:
        df_raw = pd.DataFrame()
        scraped_urls = set()
        
    results = []
    count = 0
    
    for index, row in df_todo.iterrows():
        url = row['product_url']
        if url in scraped_urls:
            continue
            
        print(f"[{count+1}/{len(df_todo)}] Scraping {url}")
        product_data = scrape_product(url)
        
        if product_data:
            results.append(product_data)
            count += 1
            
        # Save every 10 products
        if count % 10 == 0 and results:
            df_new = pd.DataFrame(results)
            df_raw = pd.concat([df_raw, df_new], ignore_index=True)
            df_raw.to_csv(raw_file, index=False)
            results = []
            print(f"Saved {len(df_raw)} products so far.")
            
        # Respectful delay
        time.sleep(1)
        
    if results:
        df_new = pd.DataFrame(results)
        df_raw = pd.concat([df_raw, df_new], ignore_index=True)
        df_raw.to_csv(raw_file, index=False)
        
    print(f"Finished scraping. Total products: {len(df_raw)}")

if __name__ == "__main__":
    main()
