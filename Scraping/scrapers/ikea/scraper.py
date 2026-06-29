import asyncio
import csv
import json
import os
import time
from datetime import datetime

import httpx

API_URL = "https://sik.search.blue.cdtapps.com/eg/en/search?c=sr&v=20250507"
PAGE_SIZE = 72
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PROGRESS_FILE = os.path.join(DATA_DIR, "listing_progress.json")
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Content-Type": "application/json; charset=utf-8",
    "Origin": "https://www.ikea.com",
    "Referer": "https://www.ikea.com/eg/en/search/",
    "Accept": "application/json, text/plain, */*",
}

SEARCH_PAYLOAD = {
    "searchParameters": {"input": "", "type": "QUERY"},
    "allowAutocorrect": True,
    "isUserLoggedIn": False,
    "isB2B": False,
    "listingABTest": False,
    "components": [{
        "component": "PRIMARY_AREA",
        "columns": 4,
        "types": {"main": "PRODUCT", "breakouts": ["PLANNER", "CATEGORY", "CONTENT", "MATTRESS_WARRANTY", "FINANCIAL_SERVICES"]},
        "filterConfig": {"subcategories-style": "tree-navigation", "max-num-filters": 7, "presetFilters": False},
        "window": {"size": PAGE_SIZE, "offset": 0},
        "allVariants": False,
        "forceFilterCalculation": True,
    }]
}


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {"offset": 0, "products_scraped": 0}


def save_progress(state):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(state, f, indent=2)


def extract_product(product):
    sales_price = product.get("salesPrice", {})
    cat_path = product.get("categoryPath", [])

    return {
        "product_id": product.get("id", ""),
        "product_name": product.get("name", ""),
        "type_name": product.get("typeName", ""),
        "current_price": sales_price.get("numeral", ""),
        "currency_code": sales_price.get("currencyCode", ""),
        "discount_tag": sales_price.get("tag", ""),
        "product_url": product.get("pipUrl", ""),
        "image_url": product.get("mainImageUrl", ""),
        "category_path": " > ".join(c["name"] for c in cat_path),
        "category_name": cat_path[0]["name"] if cat_path else "",
        "subcategory_name": cat_path[1]["name"] if len(cat_path) > 1 else "",
        "leaf_category": cat_path[-1]["name"] if cat_path else "",
        "rating_value": product.get("ratingValue", ""),
        "rating_count": product.get("ratingCount", ""),
        "item_no": product.get("itemNo", ""),
        "item_measurement": product.get("itemMeasureReferenceText", ""),
    }


async def fetch_page(client, offset):
    payload = dict(SEARCH_PAYLOAD)
    payload["components"][0]["window"]["offset"] = offset

    r = await client.post(API_URL, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()

    result = data["results"][0]
    items = result.get("items", [])
    metadata = result.get("metadata", {})
    total = metadata.get("max", 0)

    products = []
    for item in items:
        if item.get("type") != "PRODUCT":
            continue
        products.append(extract_product(item.get("product", {})))

    return products, total


async def main():
    progress = load_progress()
    offset = progress["offset"]
    total_scraped = progress["products_scraped"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(DATA_DIR, f"ikea_products_{timestamp}.csv")

    fieldnames = [
        "product_id", "product_name", "type_name", "current_price",
        "currency_code", "discount_tag", "product_url", "image_url",
        "category_path", "category_name", "subcategory_name", "leaf_category",
        "rating_value", "rating_count", "item_no", "item_measurement",
    ]

    csvfile = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    async with httpx.AsyncClient() as client:
        # First request to get total
        products, total = await fetch_page(client, offset)
        if offset == 0:
            print(f"Total products to scrape: {total}")
            print(f"Estimated pages: {(total + PAGE_SIZE - 1) // PAGE_SIZE}")

        while offset < total:
            try:
                products, total = await fetch_page(client, offset)
            except Exception as e:
                print(f"Error at offset {offset}: {e}")
                save_progress({"offset": offset, "products_scraped": total_scraped})
                print("Progress saved. Exiting.")
                break

            for p in products:
                writer.writerow(p)
            total_scraped += len(products)
            csvfile.flush()

            print(f"Offset {offset:>5}: {len(products):>3} products (total: {total_scraped:>5} / {total})")

            save_progress({"offset": offset + PAGE_SIZE, "products_scraped": total_scraped})
            offset += PAGE_SIZE

            await asyncio.sleep(0.5)

    csvfile.close()
    os.remove(PROGRESS_FILE)
    print(f"\nDone! {total_scraped} products saved to {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
