"""Noon scraper - webfetch-assisted workflow

Workflow:
1. Run: python batch_scraper.py --plan          -> generates url_plan.json
2. Run: python batch_scraper.py --next           -> prints next URL to fetch
3. Fetch that URL with webfetch, save to fetched/{N}.html
4. Run: python batch_scraper.py --process        -> parses all fetched .html files into CSV
5. Repeat steps 2-4 until all pages done
"""
import re, csv, json, os, sys
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import quote

BASE_URL = "https://www.noon.com/egypt-en"
OUTPUT_CSV = "noon_products_v2.csv"
PLAN_FILE = "url_plan_v2.json"
PROGRESS_FILE = "progress_v2.json"
FETCHED_DIR = "fetched_v2"

# === URL PLAN ===

SEARCH_QUERIES = [
    # Electronics
    "phone", "mobile", "smartphone", "laptop", "computer", "tablet", "ipad",
    "tv", "television", "monitor", "headphones", "earphones", "speaker",
    "camera", "watch", "smartwatch", "fitness tracker", "gaming console",
    "gaming chair", "gaming mouse", "gaming keyboard", "printer", "scanner",
    "router", "power bank", "charger", "usb cable", "hard drive", "ssd",
    "memory card", "projector", "soundbar", "webcam", "microphone",
    # Women Fashion
    "women dress", "women top", "women t-shirt", "women blouse",
    "women shoes", "women bag", "women jeans", "women jacket",
    "women pants", "women skirt", "women shorts", "women sweater",
    "women cardigan", "women coat", "jumpsuit", "leggings",
    "sports bra", "activewear", "sandals", "heels", "flats",
    "sneakers women", "boots women", "tote bag", "crossbody bag",
    "shoulder bag", "clutch", "wallet women", "belt women",
    "sunglasses women", "scarf", "hat women",
    # Men Fashion
    "men shirt", "men t-shirt", "men jeans", "men shoes", "men jacket",
    "men suit", "men blazer", "men pants", "men shorts", "men sweater",
    "men hoodie", "men polo", "men sneakers", "boots men",
    "loafers men", "sandals men", "slip ons", "backpack men",
    "wallet men", "belt men", "sunglasses men", "tie", "bow tie",
    "men sportswear", "track pants", "football shoes",
    # Kids & Baby
    "kids clothes", "kids shoes", "kids jacket", "kids pants",
    "kids t-shirt", "kids dress", "kids sneakers", "kids backpack",
    "baby", "baby diaper", "baby wipes", "baby stroller",
    "baby car seat", "baby clothes", "baby bodysuit", "baby shoes",
    "baby feeding", "baby bottle", "baby food", "baby bath",
    "baby toy", "baby crib", "baby mattress", "baby monitor",
    # Home Appliances
    "refrigerator", "washing machine", "air conditioner", "microwave",
    "blender", "mixer", "toaster", "air fryer", "coffee maker", "iron",
    "vacuum", "fan", "heater", "water dispenser", "dishwasher",
    "oven", "electric kettle", "juicer", "food processor",
    "rice cooker", "pressure cooker", "slow cooker", "bread maker",
    "hair dryer", "hair straightener", "hair curler", "shaver",
    # Furniture & Home
    "sofa", "chair", "table", "bed", "mattress", "desk", "cabinet",
    "bookshelf", "dining table", "coffee table", "nightstand",
    "dresser", "wardrobe", "shelf", "bean bag", "office chair",
    "gaming desk", "tv stand", "shoe rack", "storage bin",
    "curtain", "carpet", "rug", "lamp", "chandelier",
    "wall art", "mirror", "vase", "clock", "cushion",
    # Kitchen & Dining
    "pot", "pan", "plate", "cup", "glass", "bottle", "mug",
    "bowl", "knife set", "cutting board", "bakeware", "cookware set",
    "dinner set", "utensil set", "food container", "water bottle",
    "lunch box", "thermos", "strainer", "measuring cup",
    # Beauty & Personal Care
    "makeup", "foundation", "lipstick", "mascara", "eyeshadow",
    "eyeliner", "lip gloss", "blush", "concealer", "makeup brush",
    "makeup remover", "nail polish", "lip balm",
    "perfume", "cologne", "deodorant", "body spray",
    "shampoo", "conditioner", "hair mask", "hair oil", "hair spray",
    "hair color", "hair gel", "hair serum",
    "skincare", "moisturizer", "sunscreen", "face wash", "serum",
    "face cream", "eye cream", "toner", "face mask", "body lotion",
    "body wash", "hand cream", "lip care", "sunscreen spray",
    "men grooming", "beard oil", "shaving cream", "razor",
    # Health & Fitness
    "vitamin", "supplement", "protein", "massage gun", "yoga mat",
    "dumbbell", "kettlebell", "resistance band", "treadmill",
    "exercise bike", "jump rope", "gym gloves",
    "blood pressure monitor", "thermometer", "weighing scale",
    # Sports & Outdoors
    "sport equipment", "football", "basketball", "tennis racket",
    "swimming goggles", "bicycle", "helmet", "skateboard",
    "camping tent", "sleeping bag", "hiking shoes",
    # Toys & Games
    "toy", "game", "puzzle", "lego", "doll", "action figure",
    "board game", "card game", "remote control car", "drone",
    "toy car", "stuffed animal", "educational toy",
    "building blocks", "art set", "coloring book",
    # Stationery & Books
    "book", "notebook", "pen", "pencil", "eraser", "stapler",
    "marker", "highlighter", "tape", "glue", "scissors",
    "file folder", "binder", "calculator", "desk organizer",
    # Automotive
    "car accessory", "car charger", "car perfume", "car cover",
    "car mat", "seat cover", "steering wheel cover",
    "engine oil", "car wax", "car cleaner", "dash cam",
    "car音响", "car gps",
    # Grocery & Beverages
    "oil", "rice", "pasta", "cooking oil", "water", "juice",
    "tea", "coffee", "sugar", "flour", "salt", "spice",
    "chips", "chocolate", "candy", "biscuit", "cereal",
    "honey", "jam", "sauce", "ketchup", "mayonnaise",
    "canned food", "olive oil", "vinegar", "soup",
    # Pets
    "pet food", "dog food", "cat food", "pet toy", "pet bed",
    "dog leash", "cat litter",
    # General
    "all", "new", "sale", "best seller", "gift", "offer",
    "discount", "clearance", "ramadan", "eid",
    "back to school", "summer", "winter",
    # Arabic
    "\u0645\u062d\u0645\u0648\u0644", "\u0644\u0627\u0628 \u062a\u0648\u0628",
    "\u062a\u0644\u0641\u0632\u064a\u0648\u0646", "\u0633\u0645\u0627\u0639\u0627\u062a",
    "\u0645\u0644\u0627\u0628\u0633", "\u0627\u062d\u0630\u064a\u0629",
    "\u0633\u0627\u0639\u0627\u062a", "\u0639\u0637\u0648\u0631", "\u0645\u0643\u064a\u0627\u062c",
    "\u0644\u0639\u0628", "\u0643\u062a\u0628", "\u0627\u062c\u0647\u0632\u0629",
    "\u0645\u0637\u0628\u062e", "\u0627\u062b\u0627\u062b",
    "\u0645\u0643\u064a\u0641", "\u062b\u0644\u0627\u062c\u0629",
    "\u063a\u0633\u0627\u0644\u0629", "\u0645\u0643\u0646\u0633\u0629",
    "\u0642\u0647\u0648\u0629", "\u0634\u0627\u064a",
    "\u0639\u0635\u064a\u0631", "\u0632\u064a\u062a", "\u0623\u0631\u0632",
    "\u062d\u0644\u064a\u0628", "\u062e\u0628\u0632",
    "\u062d\u0641\u0627\u0621\u0627\u062a", "\u0645\u0643\u064a\u0627\u062c",
    "\u0639\u0637\u0648\u0631 \u0631\u062c\u0627\u0644\u064a\u0629",
    "\u0641\u0633\u062a\u0627\u0646", "\u0628\u0646\u0637\u0644\u0648\u0646",
    "\u062c\u0627\u0643\u064a\u062a", "\u0642\u0645\u064a\u0635",
]

CATEGORY_URLS = [
    ("electronics-mobiles", "electronics-and-mobiles"),
    ("fashion", "fashion"),
    ("beauty-fragrance", "beauty-and-fragrance"),
    ("home-appliances", "home-and-appliances"),
    ("baby", "baby"),
    ("toys-games", "toys-and-games"),
    ("supermarket", "supermarket"),
    ("automotive", "automotive"),
    ("sports-outdoors", "sports-and-outdoors"),
    ("stationery-books", "stationery-and-books"),
    ("health-nutrition", "health-and-nutrition"),
    ("men-fashion", "men-fashion"),
    ("women-fashion", "women-fashion"),
    ("kids-fashion", "kids-fashion"),
    ("phones-tablets", "phones-and-tablets"),
    ("laptops", "laptops"),
    ("tv-video", "tv-and-video"),
    ("camera", "camera-photo-and-video"),
    ("audio", "audio"),
    ("gaming", "gaming"),
    ("watches", "watches"),
    ("fragrance", "fragrance"),
    ("makeup", "makeup"),
    ("skincare", "skincare"),
    ("haircare", "haircare"),
    ("kitchen-appliances", "kitchen-appliances"),
    ("furniture", "furniture"),
    ("home-decor", "home-decor"),
    ("tools", "tools-and-home-improvement"),
    ("pet-supplies", "pet-supplies"),
    ("luggage", "luggage"),
    ("sport-shoes", "sport-shoes"),
    ("diet-supplements", "diet-and-supplements"),
]

MAX_PAGES_PER_QUERY = 2
MAX_PAGES_PER_CATEGORY = 1

def generate_plan():
    plan = []
    idx = 0
    for q in SEARCH_QUERIES:
        for page in range(1, MAX_PAGES_PER_QUERY + 1):
            url = f"{BASE_URL}/search?q={quote(q)}&limit=200&page={page}"
            plan.append({"id": idx, "type": "search", "query": q, "page": page, "url": url})
            idx += 1
    for cat_name, cat_slug in CATEGORY_URLS:
        for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
            url = f"{BASE_URL}/{cat_slug}?limit=200&page={page}"
            plan.append({"id": idx, "type": "category", "category": cat_name, "page": page, "url": url})
            idx += 1
    with open(PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump({"total": len(plan), "pages": plan}, f)
    print(f"Plan generated: {len(plan)} URLs ({idx} total)")
    return plan

def load_plan():
    if not os.path.exists(PLAN_FILE):
        return None
    with open(PLAN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {"fetched": [], "extracted": 0}
    with open(PROGRESS_FILE, "r") as f:
        return json.load(f)

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

# === EXTRACTION ===

def extract_products_from_html(html, category="search"):
    soup = BeautifulSoup(html, "lxml")
    boxes = soup.select('[data-qa="plp-product-box"]')
    products = []
    seen_ids = set()
    for box in boxes:
        a_tag = box.find("a")
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        if "/p/" not in href:
            continue
        pid_match = re.search(r'/([A-Z0-9]{8,25}[A-Z])/p/', href)
        if not pid_match:
            continue
        pid = pid_match.group(1)
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        full_url = "https://www.noon.com" + href
        title = ""
        h2 = box.select_one('[data-qa="plp-product-box-name"]')
        if h2:
            title = h2.get_text(strip=True)
        if not title:
            img_div = box.select_one('[data-qa^="productImagePLP_"]')
            if img_div:
                title = img_div.get("data-qa", "").replace("productImagePLP_", "", 1).strip()

        current_price = ""
        amount_el = box.select_one('[class*="amount"]')
        if amount_el:
            try:
                current_price = float(amount_el.get_text(strip=True).replace(",", ""))
            except:
                current_price = amount_el.get_text(strip=True)

        old_price = ""
        old_el = box.select_one('[class*="oldPrice"]')
        if old_el:
            try:
                old_price = float(old_el.get_text(strip=True).replace(",", ""))
            except:
                old_price = old_el.get_text(strip=True)

        discount = ""
        disc_el = box.select_one('[class*="discountText"]')
        if disc_el:
            discount = disc_el.get_text(strip=True)
        if not discount:
            pct_el = box.select_one('[class*="PriceDiscount"]')
            if pct_el:
                discount = pct_el.get_text(strip=True)

        products.append({
            "title": title, "current_price": current_price,
            "old_price": old_price, "discount": discount,
            "url": full_url, "category": category, "product_id": pid,
        })
    return products

def append_to_csv(products):
    if not products:
        return 0
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["title", "current_price", "old_price", "discount", "url", "category", "product_id"])
        if not file_exists:
            w.writeheader()
        for p in products:
            w.writerow(p)
    return len(products)

def get_csv_count():
    if not os.path.exists(OUTPUT_CSV):
        return 0
    with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
        return sum(1 for _ in f) - 1

def deduplicate_csv():
    if not os.path.exists(OUTPUT_CSV):
        return
    with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    seen = set()
    unique = []
    for r in rows:
        pid = r.get("product_id", "")
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(r)
    if len(unique) < len(rows):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["title", "current_price", "old_price", "discount", "url", "category", "product_id"])
            w.writeheader()
            w.writerows(unique)
        print(f"  Dedup: {len(rows)} -> {len(unique)} rows")
    return len(unique)

# === COMMANDS ===

def cmd_plan():
    generate_plan()

def cmd_next():
    plan_data = load_plan()
    if not plan_data:
        print("No plan. Run --plan first.")
        return
    progress = load_progress()
    fetched_set = set(progress.get("fetched", []))
    for page in plan_data["pages"]:
        if page["id"] not in fetched_set:
            print(json.dumps(page))
            return
    print("ALL DONE")
    # Show summary
    count = get_csv_count()
    print(f"Total products collected: {count}")

def cmd_process():
    plan_data = load_plan()
    if not plan_data:
        print("No plan. Run --plan first.")
        return
    progress = load_progress()
    fetched_set = set(progress.get("fetched", []))

    if not os.path.exists(FETCHED_DIR):
        print(f"No {FETCHED_DIR}/ directory found.")
        return

    new_fetched = []
    for fname in sorted(os.listdir(FETCHED_DIR)):
        if not fname.endswith(".html"):
            continue
        stem = fname.replace(".html", "")
        try:
            pid = int(stem)
        except:
            continue
        if pid in fetched_set:
            continue
        new_fetched.append(pid)

    if not new_fetched:
        print("No new files to process.")
        return

    print(f"Found {len(new_fetched)} new files to process")
    total_products = 0
    for pid in sorted(new_fetched):
        fpath = os.path.join(FETCHED_DIR, f"{pid}.html")
        with open(fpath, "r", encoding="utf-8") as f:
            raw = f.read()
        # Get category info from plan
        page_info = next((p for p in plan_data["pages"] if p["id"] == pid), None)
        category = page_info["query"] if page_info and page_info["type"] == "search" else (page_info.get("category", "unknown") if page_info else "unknown")
        products = extract_products_from_html(raw, category=category)
        n = append_to_csv(products)
        total_products += n
        if n == 0:
            print(f"  [{pid}] {page_info.get('url','?')[:80]}... -> 0 products (empty/dead)")
        else:
            print(f"  [{pid}] {page_info.get('url','?')[:80]}... -> {n} products")
        fetched_set.add(pid)
        progress["fetched"] = list(fetched_set)
        progress["extracted"] = get_csv_count()
        save_progress(progress)

    print(f"\nProcessed {len(new_fetched)} files, extracted {total_products} products")
    count = get_csv_count()
    print(f"Total in CSV: {count}")
    deduplicate_csv()
    count = get_csv_count()
    print(f"After dedup: {count}")

def cmd_status():
    plan_data = load_plan()
    if not plan_data:
        print("No plan generated yet.")
        return
    progress = load_progress()
    fetched = len(progress.get("fetched", []))
    total = plan_data["total"]
    count = get_csv_count()
    print(f"Plan: {total} URLs total")
    print(f"Fetched: {fetched} pages ({fetched/total*100:.1f}%)")
    print(f"Products in CSV: {count}")
    print(f"Target: 70,000 - need {max(0, 70000 - count)} more")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python batch_scraper.py [--plan | --next | --process | --status]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "--plan":
        cmd_plan()
    elif cmd == "--next":
        cmd_next()
    elif cmd == "--process":
        cmd_process()
    elif cmd == "--status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
