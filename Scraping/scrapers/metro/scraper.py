import requests
from bs4 import BeautifulSoup
import csv
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from threading import Lock
import os

BASE_URL = "https://www.metro-markets.com"
OUTPUT = "metro_products_full.csv"
MAX_WORKERS = 20
CHECKPOINT_FILE = "metro_checkpoint.txt"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

all_products = {}
lock = Lock()
scanned_ids = set()

def extract_from_product_page(pid):
    """Try to access and extract data from a product page by ID"""
    url = f"{BASE_URL}/product/p/{pid}"
    try:
        r = session.get(url, timeout=15, allow_redirects=True)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        # Check if this is actually a product page or a redirect
        title_tag = soup.select_one("h1") or soup.select_one("h5")
        if not title_tag:
            return None
        title = title_tag.get_text(strip=True)
        if not title or title == "":
            return None
        # Price
        price_tag = soup.select_one("p.after") or soup.select_one("span.price") or soup.select_one(".current-price")
        current_price = ""
        if price_tag:
            m = re.search(r"([\d.]+)", price_tag.get_text(strip=True).replace(",", ""))
            if m:
                current_price = m.group(1)
        old_price = ""
        old_tag = soup.select_one("p.before") or soup.select_one(".old-price")
        if old_tag:
            m = re.search(r"([\d.]+)", old_tag.get_text(strip=True).replace(",", ""))
            if m:
                old_price = m.group(1)
        discount = ""
        disc_tag = soup.select_one("div.discound")
        if disc_tag:
            m = re.search(r"([\d.]+)", disc_tag.get_text(strip=True))
            if m:
                discount = m.group(1) + "%"
        # Category from breadcrumb
        category = ""
        breadcrumb = soup.select_one("ol.breadcrumb")
        if breadcrumb:
            items = breadcrumb.select("li.breadcrumb-item a")
            names = [a.get_text(strip=True) for a in items if a.get_text(strip=True) != "Home"]
            category = " > ".join(names)
        return {
            "title": title,
            "current_price": current_price,
            "old_price": old_price,
            "discount": discount,
            "url": r.url,
            "category": category,
        }
    except:
        return None

# First, get all known products from search (the clean way)
def scrape_search_pages():
    r = session.get(f"{BASE_URL}/search?key=", timeout=30)
    soup = BeautifulSoup(r.text, "lxml")
    pagination = soup.select_one("ul.pagination")
    total_pages = 1
    if pagination:
        for link in pagination.select("a.page-link"):
            m = re.search(r"page=(\d+)", link.get("href", ""))
            if m:
                p = int(m.group(1))
                if p > total_pages:
                    total_pages = p
    print(f"Scraping {total_pages} search pages...")
    for page in range(1, total_pages + 1):
        try:
            r = session.get(f"{BASE_URL}/search?key=&page={page}", timeout=30)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select("div.product-card.card"):
                try:
                    pid = card.get("data-id")
                    if pid:
                        scanned_ids.add(int(pid))
                    title_tag = card.select_one("h5")
                    if not title_tag:
                        continue
                    title = title_tag.get_text(strip=True)
                    link_tag = card.select_one("a[href*='/product/']")
                    if not link_tag:
                        continue
                    product_url = link_tag.get("href", "")
                    if product_url.startswith("/"):
                        product_url = BASE_URL + product_url
                    price_tag = card.select_one("p.after")
                    current_price = ""
                    if price_tag:
                        m = re.search(r"([\d.]+)", price_tag.get_text(strip=True).replace(",", ""))
                        if m:
                            current_price = m.group(1)
                    old_price = ""
                    old_tag = card.select_one("p.before")
                    if old_tag:
                        m = re.search(r"([\d.]+)", old_tag.get_text(strip=True).replace(",", ""))
                        if m:
                            old_price = m.group(1)
                    discount = ""
                    disc_tag = card.select_one("div.discound")
                    if disc_tag:
                        m = re.search(r"([\d.]+)", disc_tag.get_text(strip=True))
                        if m:
                            discount = m.group(1) + "%"
                    with lock:
                        if product_url not in all_products:
                            all_products[product_url] = {
                                "title": title,
                                "current_price": current_price,
                                "old_price": old_price,
                                "discount": discount,
                                "url": product_url,
                                "category": "All Products",
                            }
                except:
                    pass
        except:
            pass
        if page % 50 == 0:
            with lock:
                print(f"  Search page {page}/{total_pages}, {len(all_products)} products...")
    return total_pages

def brute_force_products(start_id, end_id):
    """Brute-force check a range of product IDs"""
    found = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {}
        for pid in range(start_id, end_id + 1):
            if pid in scanned_ids:
                continue
            f = ex.submit(extract_from_product_page, pid)
            futures[f] = pid
            time.sleep(0.05)
        for f in as_completed(futures):
            pid = futures[f]
            try:
                result = f.result(timeout=20)
                if result:
                    with lock:
                        if result["url"] not in all_products:
                            all_products[result["url"]] = result
                            found += 1
            except:
                pass
    return found

def save_checkpoint(count):
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(count))

if __name__ == "__main__":
    print("=" * 60)
    print("METRO-MARKETS PRODUCT SCRAPER")
    print("=" * 60)
    
    # Phase 1: Scrape all search pages (known products)
    print("\nPhase 1: Scraping search pages...")
    total_pages = scrape_search_pages()
    print(f"  Search complete: {len(all_products)} products from {total_pages} pages")
    
    # Determine max known ID
    max_known = max(scanned_ids) if scanned_ids else 0
    print(f"  Max known product ID: {max_known}")
    print(f"  Known product IDs count: {len(scanned_ids)}")
    
    # Phase 2: Brute force IDs not in known set
    print(f"\nPhase 2: Brute-forcing unseen IDs (1 to {max_known})...")
    found_extras = brute_force_products(1, max_known)
    print(f"  Found {found_extras} additional products")
    
    # Phase 3: Continue beyond max known
    print(f"\nPhase 3: Checking IDs beyond {max_known}...")
    far_found = brute_force_products(max_known + 1, max_known + 20000)
    print(f"  Found {far_found} products beyond max known")
    
    # Save
    fieldnames = ["title", "current_price", "old_price", "discount", "url", "category"]
    with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in all_products.values():
            writer.writerow(p)
    
    print(f"\n{'=' * 60}")
    print(f"FINAL: {len(all_products)} products saved to {OUTPUT}")
    print(f"{'=' * 60}")
