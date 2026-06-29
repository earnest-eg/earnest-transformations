import csv
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

BASE_URL = "https://kimostore.net"
OUTPUT_DIR = Path("B:/depi/scraping/kimostore/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_COLUMNS = [
    "title", "name", "product_current_price", "product_old_price",
    "product_discount", "product_url", "product_image_url", "product_seller",
    "product_availability", "product_category", "product_subcategory",
    "product_unit", "product_weight", "scraping_time", "timestamp_timezone",
    "product_brand", "product_ram", "product_storage"
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://kimostore.net/",
})

CATEGORY_MAP = {
    "motherboard": "electronics > computer > components",
    "processor": "electronics > computer > components",
    "graphics card": "electronics > computer > components",
    "ram": "electronics > computer > components",
    "internal hard disk": "electronics > computer > storage",
    "monitor": "electronics > computer > monitors",
    "computer case": "electronics > computer > components",
    "pc power supply": "electronics > computer > components",
    "tower pc": "electronics > computer > desktops",
    "desktop pc": "electronics > computer > desktops",
    "all in one": "electronics > computer > desktops",
    "laptops": "electronics > computer > laptops",
    "laptop": "electronics > computer > laptops",
    "mobile phone": "electronics > mobiles",
    "tablets": "electronics > tablets",
    "smart watch": "electronics > wearables",
    "earphone": "electronics > audio",
    "headphone": "electronics > audio",
    "speaker": "electronics > audio",
    "sound": "electronics > audio",
    "television": "electronics > tv",
    "printer": "electronics > computer > peripherals",
    "scanner": "electronics > computer > peripherals",
    "router": "electronics > networking",
    "access point": "electronics > networking",
    "switch": "electronics > networking",
    "network": "electronics > networking",
    "cctv": "electronics > security",
    "security": "electronics > security",
    "surveillance": "electronics > security",
    "dvr": "electronics > security",
    "nvr": "electronics > security",
    "cashier": "electronics > pos",
    "barcode": "electronics > pos",
    "receipt printer": "electronics > pos",
    "hair": "personal care > hair care",
    "straightener": "personal care > hair care",
    "curling": "personal care > hair care",
    "epilator": "personal care > grooming",
    "personal care": "personal care",
    "oven": "home > kitchen",
    "microwave": "home > kitchen",
    "refrigerator": "home > appliances",
    "washing machine": "home > appliances",
    "air conditioner": "home > appliances",
    "vacuum": "home > appliances",
    "fan": "home > appliances",
    "air cooler": "home > appliances",
    "water dispenser": "home > appliances",
    "heater": "home > appliances",
    "kitchen": "home > kitchen",
    "blender": "home > kitchen",
    "mixer": "home > kitchen",
    "air fryer": "home > kitchen",
    "coffee": "home > kitchen",
    "sandwich": "home > kitchen",
    "kettle": "home > kitchen",
    "bag": "accessories > bags",
    "backpack": "accessories > bags",
    "battery": "electronics > computer > components",
    "keyboard": "electronics > computer > peripherals",
    "mouse": "electronics > computer > peripherals",
    "software": "electronics > software",
    "cable": "electronics > cables",
    "charger": "electronics > accessories",
    "power bank": "electronics > accessories",
    "game": "electronics > gaming",
    "console": "electronics > gaming",
    "used": "electronics > used",
    "projector": "electronics > computer > projectors",
    "ups": "electronics > computer > components",
    "storage": "electronics > computer > storage",
    "flash": "electronics > computer > storage",
    "memory card": "electronics > computer > storage",
    "data show": "electronics > computer > projectors",
    "tv": "electronics > tv",
    "telephone": "electronics > telephones",
    "video games": "electronics > gaming",
    "gaming": "electronics > gaming",
    "photo": "electronics > accessories",
    "gimbal": "electronics > accessories",
    "stabilizer": "electronics > accessories",
    "car accessory": "electronics > accessories",
    "phone accessory": "electronics > accessories",
    "watch accessory": "electronics > wearables",
    "smart home": "home > smart home",
    "heating": "home > appliances",
    "cooling": "home > appliances",
    "power strip": "electronics > accessories",
    "hub": "electronics > computer > peripherals",
    "pdu": "electronics > networking",
    "earbuds": "electronics > audio",
    "roll": "electronics > pos",
    "sticker": "electronics > computer > peripherals",
    "label tape": "electronics > pos",
    "cartridge": "electronics > computer > peripherals",
    "toner": "electronics > computer > peripherals",
    "ink": "electronics > computer > peripherals",
    "paper": "electronics > computer > peripherals",
    "cutting plotter": "electronics > computer > peripherals",
    "time attendance": "electronics > networking",
    "fingerprint": "electronics > networking",
    "door bell": "smart home > security",
    "intercom": "electronics > networking",
    "patch panel": "electronics > networking",
    "rack": "electronics > networking",
    "keystone": "electronics > networking",
    "faceplate": "electronics > networking",
    "rj45": "electronics > networking",
    "coaxial": "electronics > security",
    "video balun": "electronics > security",
    "easy capture": "electronics > security",
    "presenter": "electronics > computer > peripherals",
    "projector screen": "electronics > computer > projectors",
    "tester": "electronics > networking",
    "rj tool": "electronics > networking",
    "converters": "electronics > computer > peripherals",
    "connectors": "electronics > computer > peripherals",
    "extender": "electronics > computer > peripherals",
    "hdmi switch": "electronics > computer > peripherals",
    "kvm": "electronics > computer > peripherals",
    "mobile rack": "electronics > computer > storage",
    "pci": "electronics > computer > components",
    "cooling pad": "electronics > computer > laptops",
    "laptop bag": "accessories > bags",
    "laptop sleeve": "accessories > bags",
    "trim": "personal care > men's grooming",
    "shaver": "personal care > men's grooming",
    "barber": "personal care > men's grooming",
    "grooming": "personal care > men's grooming",
    "men's": "personal care > men's grooming",
    "freezer": "home > appliances",
    "sewing": "home > appliances",
    "steam iron": "home > appliances",
    "garment steamer": "home > appliances",
    "juicer": "home > kitchen",
    "luggage": "electronics > accessories",
    "conduit": "home > electrical",
    "lighting": "home > lighting",
    "headlamp": "home > lighting",
    "keychain light": "home > lighting",
    "interactive": "electronics > computer > peripherals",
    "whiteboard": "electronics > computer > peripherals",
    "calculator": "electronics > computer > peripherals",
    "shampoo": "personal care > hair care",
    "conditioner": "personal care > hair care",
    "cotton candy": "home > kitchen",
    "water gun": "home > kitchen",
    "cd ": "electronics > computer > storage",
    "dvd ": "electronics > computer > storage",
}


def normalize_category(product_type: str, tags: list[str], title: str) -> tuple[str, str]:
    """Returns (category, subcategory)"""
    all_text = f"{product_type} {title} {' '.join(tags)}".lower()
    subcategory = product_type.strip() if product_type else title.split("-")[0].strip()[:50]

    for key, val in CATEGORY_MAP.items():
        if key in all_text:
            return val, subcategory

    if "laptop" in all_text:
        return "electronics > computer > laptops", subcategory
    if "computer" in all_text or "pc " in all_text:
        return "electronics > computer", subcategory
    if "mobile" in all_text or "phone" in all_text or "tablet" in all_text:
        return "electronics > mobiles", subcategory
    if "home" in all_text or "appliance" in all_text:
        return "home > appliances", subcategory
    if "tv" in all_text or "television" in all_text:
        return "electronics > tv", subcategory
    if "camera" in all_text and "security" not in all_text and "cctv" not in all_text and "surveillance" not in all_text:
        return "electronics > cameras", subcategory
    if "network" in all_text or "router" in all_text or "switch" in all_text or "ethernet" in all_text:
        return "electronics > networking", subcategory
    if "security" in all_text or "surveillance" in all_text or "cctv" in all_text:
        return "electronics > security", subcategory
    if "camera" in all_text:
        return "electronics > security", subcategory
    if "cashier" in all_text or "pos" in all_text or "barcode" in all_text:
        return "electronics > pos", subcategory
    if "audio" in all_text:
        return "electronics > audio", subcategory

    return "", subcategory


def extract_brand(vendor: str, title: str) -> str:
    if vendor and vendor not in ("", "-", "Title"):
        return vendor.strip()
    return extract_brand_from_title(title)


def extract_brand_from_title(title: str) -> str:
    known_brands = [
        "APPLE", "SAMSUNG", "XIAOMI", "HUAWEI", "LENOVO", "HP", "DELL", "ACER",
        "ASUS", "MSI", "GIGABYTE", "INTEL", "AMD", "NVIDIA", "SONY", "LG",
        "PANASONIC", "PHILIPS", "TOSHIBA", "BOSCH", "WHIRLPOOL", "ZANUSSI",
        "ARISTON", "BLACK+DECKER", "BLACK DECKER", "BRAUN", "ANKER", "JBL",
        "LOGITECH", "TP-LINK", "D-LINK", "HIKVISION", "EZVIZ", "KINGSTON",
        "SANDISK", "SEAGATE", "WD", "WESTERN DIGITAL", "CRUCIAL", "CORSAIR",
        "COOLER MASTER", "THERMALTAKE", "VIEWSONIC", "BENQ", "EPSON",
        "CANON", "BROTHER", "PANASONIC", "TEFAL", "KENWOOD", "MOULINEX",
        "ZTE", "OPPO", "REALME", "INFINIX", "TECNO", "NOKIA", "MOTOROLA",
        "HONOR", "ONEPLUS", "GOOGLE", "AMAZFIT", "GARMIN", "FITBIT",
        "ZEBRONICS", "BOAT", "NOISE", "ENERGIZER", "EVERREADY", "TESLA",
        "PROLINK", "ZKTECO", "HONEYWELL", "GSAN", "ZERO", "AULA", "REDRAGON",
        "TRUST", "GAMEMAX", "XPG", "ADATA", "TEAMGROUP", "LEXAR",
        "TRANSCEND", "MI", "MIKROTIK", "UBIQUITI", "CISCO",
        "TENDA", "MERCUSYS", "TAPO", "ARZUM", "SINBO", "HITACHI",
        "COUGAR", "RAHALA", "NANLITE", "GODOX", "JOYROOM", "BASEUS",
        "ESSAGER", "UGREEN", "ORICO", "SPRT", "BIXOLON", "STAR",
        "POINT", "MIXMAX", "GIGAMAX", "ENKE", "X-SCOOT", "MOMO",
        "MEETION", "A4TECH", "ZOTAC", "GALAX", "VIEWSONIC", "AOC",
        "XIGMATEK", "ID-COOLING", "COUGAR", "RAIJINTEK", "LIAN LI",
        "FRESNEL", "PRIFIX", "TORNADO", "ELIOS", "LAVA", "I-CONX",
        "GOLON", "ORIENT", "VGR", "RUSH BRUSH", "PIXEL", "INK",
        "SPECTRUM", "BLUE SPECTRUM", "E-TRAIN", "2B", "ZR",
        "WILD WOLF", "G-8", "G-01", "G15", "GSAN",
        "HONEYWELL", "LOGO", "RSILOU", "YONGBANG", "PASSTHROUGH",
        "NANLITE", "PERLA", "LIGHTING", "LIGHT",
    ]
    title_upper = title.upper()
    for brand in sorted(known_brands, key=len, reverse=True):
        if brand in title_upper:
            return brand.title()
    return ""


def extract_specs(title: str, body_html: str) -> dict:
    specs = {"ram": "", "storage": ""}
    text = f"{title} {body_html}"

    ram_pat = re.search(r'(\d+)\s*GB\s*(?:RAM|Ram|ram|DDR[345]\s*RAM|DDR[345])', text)
    if ram_pat:
        specs["ram"] = ram_pat.group(1) + "GB"
    if not specs["ram"]:
        ram_pat2 = re.search(r'(\d+)\s*GB\s*(?:Memory|DDR\d?|RAM)', text)
        if ram_pat2:
            specs["ram"] = ram_pat2.group(1) + "GB"
    if not specs["ram"]:
        ram_pat3 = re.search(r'(?:RAM|Ram|ram|Memory)\s*(?:Size|Support)?\s*:?\s*(\d+)\s*GB', text)
        if ram_pat3:
            specs["ram"] = ram_pat3.group(1) + "GB"

    storage_pats = [
        r'(\d+)\s*(?:GB|TB)\s*(?:SSD|HDD|NVMe|Storage|Hard\s*Disk|Internal|ROM)',
        r'(?:Storage|Hard\s*Disk|SSD|HDD)\s*:?\s*(\d+)\s*(?:GB|TB)',
    ]
    for pat in storage_pats:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1)
            unit = "TB" if "TB" in m.group(0).upper() else "GB"
            specs["storage"] = val + unit
            break

    if not specs["storage"]:
        gb_match = re.search(r'(\d+)\s*(?:GB|TB)\s*$', title.split("|")[0].strip())
        if gb_match:
            val = gb_match.group(1)
            unit = "TB" if "TB" in gb_match.group(0).upper() else "GB"
            specs["storage"] = val + unit

    return specs


def clean_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_products_page(page: int, limit: int = 250) -> list[dict] | None:
    url = f"{BASE_URL}/products.json?limit={limit}&page={page}"
    try:
        resp = SESSION.get(url, timeout=30)
        if resp.status_code == 429:
            log.warning(f"Rate limited on page {page}, waiting...")
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("products", [])
    except Exception as e:
        log.warning(f"Error fetching page {page}: {e}")
        return None


def process_product(product: dict) -> dict:
    title = product.get("title", "")
    vendor = product.get("vendor", "")
    product_type = product.get("product_type", "")
    tags = product.get("tags", []) or []
    body_html = clean_html(product.get("body_html", ""))
    handle = product.get("handle", "")
    product_url = f"{BASE_URL}/products/{handle}"

    variants = product.get("variants", [])
    images = product.get("images", [])

    variant = variants[0] if variants else {}

    current_price = variant.get("price", "")
    old_price = variant.get("compare_at_price", "")

    if current_price:
        try:
            cp = float(current_price)
            current_price = str(int(cp)) if cp == int(cp) else f"{cp:.2f}"
        except ValueError:
            current_price = str(current_price)

    if old_price:
        try:
            op = float(old_price)
            old_price = str(int(op)) if op == int(op) else f"{op:.2f}"
        except ValueError:
            old_price = str(old_price)

    discount = ""
    if old_price and old_price != "nan" and current_price and current_price != "nan":
        try:
            old_val = float(old_price)
            curr_val = float(current_price)
            if old_val > curr_val and old_val > 0:
                discount = f"{((old_val - curr_val) / old_val) * 100:.3f}%"
        except ValueError:
            pass

    image_url = ""
    if images:
        image_url = images[0].get("src", "")
        if image_url and not image_url.startswith("http"):
            image_url = urljoin(BASE_URL, image_url)

    available = variant.get("available", True)
    availability = "in_stock" if available else "out_of_stock"

    category, subcategory = normalize_category(product_type, tags, title)
    brand = extract_brand(vendor, title)
    specs = extract_specs(title, body_html)

    scraping_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    row = {
        "title": title,
        "name": title,
        "product_current_price": current_price,
        "product_old_price": old_price,
        "product_discount": discount,
        "product_url": product_url,
        "product_image_url": image_url,
        "product_seller": "Kimo Store",
        "product_availability": availability,
        "product_category": category,
        "product_subcategory": subcategory,
        "product_unit": "",
        "product_weight": "",
        "scraping_time": scraping_time,
        "timestamp_timezone": "Africa/Cairo",
        "product_brand": brand,
        "product_ram": specs["ram"],
        "product_storage": specs["storage"],
    }

    # Extract unit/weight from title
    unit_match = re.search(r'(\d+\s*(?:pcs|Pcs|PCS|pieces|Pack|pack|Count|count|Bottles|bottles))', title)
    if unit_match:
        row["product_unit"] = unit_match.group(1)

    weight_match = re.search(r'(\d+\.?\d*\s*(?:g|kg|ml|l|L|cm|mm|inch))', body_html + " " + title, re.IGNORECASE)
    if weight_match:
        row["product_weight"] = weight_match.group(1)

    return row


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[TARGET_COLUMNS]

    df["title"] = df["title"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    df["product_current_price"] = df["product_current_price"].astype(str).str.strip()
    df["product_url"] = df["product_url"].astype(str).str.strip()

    before = len(df)
    df = df[df["title"].notna() & (df["title"] != "")]
    df = df[df["product_current_price"].notna() & (df["product_current_price"] != "")]
    df = df[df["product_url"].notna() & (df["product_url"] != "")]
    df = df[~df["product_url"].astype(str).str.contains(r'/products/\d+$', regex=True)]
    after = len(df)
    log.info(f"Removed {before - after} rows with missing/invalid data")

    return df


def export_files(df: pd.DataFrame):
    csv_path = OUTPUT_DIR / "kimostore_products.csv"
    json_path = OUTPUT_DIR / "kimostore_products.json"
    zip_path = OUTPUT_DIR / "kimostore_products.zip"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info(f"CSV exported: {csv_path} ({len(df)} rows)")

    df.to_json(json_path, orient="records", force_ascii=False, indent=2)
    log.info(f"JSON exported: {json_path}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(csv_path, csv_path.name)
        zf.write(json_path, json_path.name)
    log.info(f"ZIP archive: {zip_path}")

    return csv_path, json_path, zip_path


def validate(df: pd.DataFrame) -> dict:
    issues = []
    if len(df.columns) != 18:
        issues.append(f"Expected 18 columns, got {len(df.columns)}")
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            issues.append(f"Missing column: {col}")

    non_numeric = df[~df["product_current_price"].astype(str).str.match(r'^\d*\.?\d*$') & (df["product_current_price"] != "")].shape[0]
    if non_numeric > 0:
        issues.append(f"{non_numeric} rows have non-numeric current prices")

    missing_urls = df[df["product_url"].astype(str) == ""].shape[0]
    if missing_urls > 0:
        issues.append(f"{missing_urls} rows have empty URLs")

    return {
        "row_count": len(df),
        "columns": list(df.columns),
        "columns_match": list(df.columns) == TARGET_COLUMNS,
        "issues": issues,
        "valid": len(issues) == 0
    }


def main():
    log.info("=== Kimo Store Scraper v2 (Shopify JSON API) ===")
    start_time = time.time()

    all_products = []
    page = 1
    consecutive_empty = 0
    retry_count = 0
    max_retries = 5

    log.info("Fetching all products from Shopify JSON API...")
    while True:
        products = fetch_products_page(page)
        if products is None:
            retry_count += 1
            if retry_count > max_retries:
                log.error("Too many failures, stopping")
                break
            wait = retry_count * 10
            log.info(f"Retry {retry_count}/{max_retries}, waiting {wait}s...")
            time.sleep(wait)
            continue

        retry_count = 0

        if not products:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                log.info(f"No more products after page {page - 1}")
                break
            page += 1
            continue

        consecutive_empty = 0
        all_products.extend(products)
        log.info(f"Page {page}: got {len(products)} products (total: {len(all_products)})")

        if len(products) < 250:
            log.info(f"Last page reached ({len(products)} < 250)")
            break

        page += 1
        time.sleep(0.3)

    log.info(f"Total raw products from API: {len(all_products)}")

    # Process all products
    results = [process_product(p) for p in all_products]
    log.info(f"Processed {len(results)} products")

    df = pd.DataFrame(results)
    log.info(f"DataFrame: {len(df)} rows")

    # Save todo list
    todo_path = OUTPUT_DIR / "todo_products.csv"
    with open(todo_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "category", "status", "error"])
        for row in results:
            writer.writerow([row["product_url"], row["product_category"], "done" if row["title"] else "failed", ""])
    log.info(f"Todo list saved: {todo_path}")

    df = clean_dataframe(df)
    csv_path, json_path, zip_path = export_files(df)

    validation = validate(df)
    log.info(f"Validation: {'PASSED' if validation['valid'] else 'FAILED'}")
    if validation.get("issues"):
        for issue in validation["issues"]:
            log.warning(f"  - {issue}")

    elapsed = time.time() - start_time
    log.info(f"=== Done in {elapsed:.1f}s ===")
    log.info(f"Total products scraped: {len(df)}")
    log.info(f"CSV: {csv_path}")
    log.info(f"JSON: {json_path}")
    log.info(f"ZIP: {zip_path}")


if __name__ == "__main__":
    main()
