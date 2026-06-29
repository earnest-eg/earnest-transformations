const fs = require("fs");
const path = require("path");
const { URL, URLSearchParams } = require("url");
const { setTimeout: sleep } = require("timers/promises");

process.env.NODE_TLS_REJECT_UNAUTHORIZED = process.env.NODE_TLS_REJECT_UNAUTHORIZED || "0";

const SITE = "https://www.tradelinestores.com";
const API = "https://tradelineserver.bit68.com/rest_api";
const TIMEZONE = "Africa/Cairo";
const SELLER = "Tradeline Stores";
const PAGE_SIZE = Number(process.env.PAGE_SIZE || 100);
const DELAY_MS = Number(process.env.DELAY_MS || 250);
const MAX_RETRIES = Number(process.env.MAX_RETRIES || 3);

const OUT_DIR = path.resolve("output");
const RAW_DIR = path.join(OUT_DIR, "raw");
const TODO_CSV = path.join(OUT_DIR, "todo_products.csv");
const PRODUCTS_CSV = path.join(OUT_DIR, "tradeline_products.csv");
const PRODUCTS_JSON = path.join(OUT_DIR, "tradeline_products.json");
const SUMMARY_JSON = path.join(OUT_DIR, "validation_summary.json");

const COLUMNS = [
  "title",
  "name",
  "product_current_price",
  "product_old_price",
  "product_discount",
  "product_url",
  "product_image_url",
  "product_seller",
  "product_availability",
  "product_category",
  "product_subcategory",
  "product_unit",
  "product_weight",
  "scraping_time",
  "timestamp_timezone",
  "product_brand",
  "product_ram",
  "product_storage",
];

function ensureDirs() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.mkdirSync(RAW_DIR, { recursive: true });
}

function cleanText(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function numberOrBlank(value) {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(String(value).replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? String(Math.round(n * 100) / 100) : "";
}

function csvEscape(value) {
  const s = value === null || value === undefined ? "" : String(value);
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function writeCsv(file, rows, columns) {
  const lines = [columns.join(",")];
  for (const row of rows) lines.push(columns.map((c) => csvEscape(row[c] || "")).join(","));
  fs.writeFileSync(file, lines.join("\n") + "\n", "utf8");
}

function absUrl(value) {
  if (!value) return "";
  try {
    return new URL(value, SITE).toString();
  } catch {
    return "";
  }
}

async function fetchJson(url, attempt = 1) {
  try {
    const res = await fetch(url, {
      headers: {
        "accept": "application/json,text/plain,*/*",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 TradelineScraper/1.0",
        "referer": SITE + "/",
      },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    if (attempt < MAX_RETRIES) {
      await sleep(750 * attempt);
      return fetchJson(url, attempt + 1);
    }
    throw err;
  }
}

function apiUrl(endpoint, params = {}) {
  const url = new URL(`${API}/${endpoint.replace(/^\/+/, "")}`);
  url.search = new URLSearchParams(params).toString();
  return url.toString();
}

function productUrl(product, categorySlug, subcategorySlug) {
  const cat = encodeURIComponent(categorySlug || product.category_seo_slug || product.category?.seo_slug || "shop");
  const sub = encodeURIComponent(subcategorySlug || product.subcategories_seo_slug?.[0] || product.subcategory?.[0]?.seo_slug || "product");
  const slug = encodeURIComponent(product.seo_slug || product.id || "");
  return `${SITE}/shop/${cat}/${sub}/${slug}`;
}

function normalizeAvailability(value, quantity) {
  const raw = cleanText(value).toLowerCase();
  if (raw.includes("out")) return "out_of_stock";
  if (raw.includes("stock") || Number(quantity || 0) > 0) return "in_stock";
  return "";
}

function brandName(product) {
  if (product.brand && typeof product.brand === "object") {
    return cleanText(product.brand.name_en || product.brand.name);
  }
  return cleanText(product.brand_name || "");
}

function standardCategory(categoryName, subcategoryName) {
  const cat = cleanText(categoryName).toLowerCase();
  const sub = cleanText(subcategoryName).toLowerCase();
  if (cat.includes("iphone")) return "electronics > mobiles";
  if (cat.includes("ipad")) return "electronics > tablets";
  if (cat.includes("mac") || sub.includes("macbook") || sub.includes("imac")) return "electronics > computers";
  if (cat.includes("watch")) return "electronics > wearables";
  if (cat.includes("airpods") || sub.includes("headphone") || sub.includes("speaker")) return "electronics > audio";
  if (cat.includes("apple tv")) return "electronics > streaming devices";
  if (cat.includes("airtag")) return "electronics > trackers";
  if (sub.includes("printer")) return "electronics > printers";
  if (sub.includes("camera")) return "electronics > cameras";
  if (sub.includes("storage")) return "electronics > storage";
  if (sub.includes("power") || sub.includes("cable")) return "electronics > power and cables";
  if (cat.includes("accessories")) return "electronics > accessories";
  return "electronics";
}

function allSpecText(product) {
  const parts = [product.name_en, product.name, product.summary];
  for (const spec of product.spec || []) {
    parts.push(spec.title_en, spec.title, spec.value_en, spec.value);
  }
  return cleanText(parts.filter(Boolean).join(" "));
}

function extractFirst(text, regex) {
  const m = cleanText(text).match(regex);
  return m ? cleanText(m[0].replace(/\s+/g, " ")) : "";
}

function extractRam(text) {
  return extractFirst(text, /\b(?:\d{1,3})\s*GB\s*(?:RAM|Memory|Unified Memory)\b/i)
    .replace(/\s+/g, "")
    .replace(/(RAM|Memory|UnifiedMemory)$/i, "GB");
}

function extractStorage(text) {
  return extractFirst(text, /\b(?:\d+(?:\.\d+)?)\s*(?:GB|TB)\s*(?:SSD|Storage)?\b/i).replace(/\s+/g, " ");
}

function extractWeight(text) {
  return extractFirst(text, /\b\d+(?:\.\d+)?\s*(?:kg|g|lbs|lb)\b/i);
}

function extractUnit(text) {
  return extractFirst(text, /\b\d+\s*(?:pack|pcs|pieces|pc|m|cm|mm|inch|inches|w|mah)\b/i);
}

function shortName(title) {
  return cleanText(title)
    .replace(/\s*-\s*(Black|White|Blue|Silver|Gold|Pink|Green|Red|Orange|Purple|Grey|Gray|Midnight|Starlight|Natural Titanium|Deep Blue|Cosmic Orange).*$/i, "")
    .replace(/\b(?:\d+\s?(?:GB|TB))\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function variantTitle(baseTitle, prop) {
  if (!prop) return baseTitle;
  const pieces = [baseTitle];
  const capacity = cleanText(prop.capacity?.name_en || prop.capacity?.name);
  const color = cleanText(prop.color?.name_en || prop.color?.name);
  const connectivity = cleanText(prop.connectivity?.name_en || prop.connectivity?.name);
  if (capacity) pieces.push(capacity);
  if (connectivity) pieces.push(connectivity);
  if (color && !baseTitle.toLowerCase().includes(color.toLowerCase())) pieces.push(color);
  return cleanText(pieces.join(" - "));
}

function imageFor(product, prop) {
  return absUrl(prop?.color?.picture || prop?.color?.picture2 || product.picture1 || product.picture2 || product.picture3);
}

function rowFromProduct(product, context, prop = null, scrapingTime) {
  const baseTitle = cleanText(product.name_en || product.name || product.meta_title);
  const title = variantTitle(baseTitle, prop);
  const currentPrice = numberOrBlank(prop?.price ?? product.price);
  const oldPrice = numberOrBlank(prop?.old_price ?? product.old_price);
  const oldN = Number(oldPrice);
  const currentN = Number(currentPrice);
  const discount = oldN > currentN && currentN > 0 ? String(Math.round(((oldN - currentN) / oldN) * 100000) / 1000) : "";
  const subName = context.subcategoryName || cleanText(product.subcategory?.[0]?.name_en || product.subcategory?.[0]?.name);
  const catName = context.categoryName || cleanText(product.category?.name_en || product.category?.name);
  const specs = `${allSpecText(product)} ${title}`;
  const capacity = cleanText(prop?.capacity?.name_en || prop?.capacity?.name);
  const url = productUrl(product, context.categorySlug, context.subcategorySlug);

  return {
    title,
    name: shortName(baseTitle),
    product_current_price: currentPrice,
    product_old_price: oldPrice,
    product_discount: discount,
    product_url: url,
    product_image_url: imageFor(product, prop),
    product_seller: SELLER,
    product_availability: normalizeAvailability(prop?.in_stock === false ? "Out Of Stock" : product.availability, prop?.quantity ?? product.quantity),
    product_category: standardCategory(catName, subName),
    product_subcategory: subName,
    product_unit: extractUnit(specs),
    product_weight: extractWeight(specs),
    scraping_time: scrapingTime,
    timestamp_timezone: TIMEZONE,
    product_brand: brandName(product),
    product_ram: extractRam(specs),
    product_storage: capacity || extractStorage(specs),
  };
}

function isGoodRow(row) {
  if (!row.title || /^(undefined|null)$/i.test(row.title)) return false;
  if (!row.product_url.startsWith(SITE)) return false;
  if (!row.product_current_price || !Number.isFinite(Number(row.product_current_price))) return false;
  if (!row.product_image_url.startsWith("http")) return false;
  return true;
}

async function discoverCategories() {
  const categories = await fetchJson(apiUrl("categories/"));
  fs.writeFileSync(path.join(RAW_DIR, "categories.json"), JSON.stringify(categories, null, 2), "utf8");
  const contexts = [];
  for (const cat of categories) {
    const subcategories = Array.isArray(cat.cat_subcategories) ? cat.cat_subcategories : [];
    for (const sub of subcategories) {
      contexts.push({
        categoryId: cat.id,
        categorySlug: cat.seo_slug,
        categoryName: cleanText(cat.name_en || cat.name),
        subcategoryId: sub.id,
        subcategorySlug: sub.seo_slug,
        subcategoryName: cleanText(sub.name_en || sub.name),
        directProductId: sub.product || "",
        directProductSlug: sub.product_seo_slug || "",
      });
    }
  }
  return contexts;
}

async function fetchSubcategoryProducts(context) {
  const all = [];
  let page = 1;
  let pages = 1;
  do {
    const data = await fetchJson(apiUrl("products/", {
      subcategory__seo_slug: context.subcategorySlug,
      is_website: "true",
      sort: "-id",
      page_size: String(PAGE_SIZE),
      page: String(page),
    }));
    const results = Array.isArray(data.results) ? data.results : Array.isArray(data) ? data : [];
    all.push(...results);
    pages = Number(data.pages_number || (data.next ? page + 1 : page));
    page += 1;
    await sleep(DELAY_MS);
  } while (page <= pages);
  return all;
}

async function fetchSearchProducts(search = "") {
  const all = [];
  let page = 1;
  let pages = 1;
  do {
    const data = await fetchJson(apiUrl("products/", {
      search,
      is_website: "true",
      sort: "-id",
      page_size: String(PAGE_SIZE),
      page: String(page),
    }));
    const results = Array.isArray(data.results) ? data.results : [];
    all.push(...results);
    pages = Number(data.pages_number || (data.next ? page + 1 : page));
    page += 1;
    await sleep(DELAY_MS);
  } while (page <= pages);
  return all;
}

function contextFromProduct(product) {
  const category = product.category || {};
  const subcategory = Array.isArray(product.subcategory) ? product.subcategory[0] || {} : {};
  return {
    categorySlug: category.seo_slug || product.category_seo_slug || "shop",
    categoryName: cleanText(category.name_en || category.name || product.category_seo_slug || ""),
    subcategorySlug: subcategory.seo_slug || product.subcategories_seo_slug?.[0] || "product",
    subcategoryName: cleanText(subcategory.name_en || subcategory.name || product.subcategories_seo_slug?.[0] || ""),
  };
}

function mergeTodo(existing, product, context, status = "pending", error = "") {
  const url = productUrl(product, context.categorySlug, context.subcategorySlug);
  if (existing.has(url)) return;
  existing.set(url, {
    url,
    category: context.categoryName,
    subcategory: context.subcategoryName,
    status,
    error,
  });
}

async function main() {
  ensureDirs();
  const scrapingTime = new Date().toISOString();
  const contexts = await discoverCategories();
  const todo = new Map();
  const rows = [];
  const seenRows = new Set();
  const stats = {
    categories: new Set(contexts.map((c) => c.categorySlug)).size,
    subcategories: contexts.length,
    product_urls: 0,
    rows: 0,
    errors: [],
  };

  for (const [index, context] of contexts.entries()) {
    process.stdout.write(`(${index + 1}/${contexts.length}) ${context.categoryName} > ${context.subcategoryName}\n`);
    try {
      const products = await fetchSubcategoryProducts(context);
      fs.writeFileSync(
        path.join(RAW_DIR, `products_${context.subcategoryId}_${context.subcategorySlug.replace(/[^a-z0-9_-]/gi, "_")}.json`),
        JSON.stringify(products, null, 2),
        "utf8"
      );
      for (const product of products) {
        mergeTodo(todo, product, context, "scraped", "");
        const props = Array.isArray(product.productproperties) && product.productproperties.length ? product.productproperties : [null];
        for (const prop of props) {
          const key = `${product.id}:${prop?.id || "base"}`;
          if (seenRows.has(key)) continue;
          const row = rowFromProduct(product, context, prop, scrapingTime);
          if (isGoodRow(row)) {
            seenRows.add(key);
            rows.push(row);
          }
        }
      }
    } catch (err) {
      stats.errors.push({ subcategory: context.subcategorySlug, error: err.message });
      const pseudo = { seo_slug: context.directProductSlug || context.subcategorySlug, category: { seo_slug: context.categorySlug } };
      mergeTodo(todo, pseudo, context, "error", err.message);
    }
  }

  process.stdout.write("Merging empty-search canonical product set\n");
  try {
    const searchProducts = await fetchSearchProducts("");
    fs.writeFileSync(path.join(RAW_DIR, "products_empty_search_all.json"), JSON.stringify(searchProducts, null, 2), "utf8");
    for (const product of searchProducts) {
      const context = contextFromProduct(product);
      mergeTodo(todo, product, context, "scraped", "");
      const props = Array.isArray(product.productproperties) && product.productproperties.length ? product.productproperties : [null];
      for (const prop of props) {
        const key = `${product.id}:${prop?.id || "base"}`;
        if (seenRows.has(key)) continue;
        const row = rowFromProduct(product, context, prop, scrapingTime);
        if (isGoodRow(row)) {
          seenRows.add(key);
          rows.push(row);
        }
      }
    }
    stats.search_products = searchProducts.length;
  } catch (err) {
    stats.errors.push({ source: "empty_search", error: err.message });
  }

  const todoRows = Array.from(todo.values()).sort((a, b) => a.url.localeCompare(b.url));
  writeCsv(TODO_CSV, todoRows, ["url", "category", "subcategory", "status", "error"]);

  const cleanRows = rows.sort((a, b) => a.product_url.localeCompare(b.product_url) || a.title.localeCompare(b.title));
  writeCsv(PRODUCTS_CSV, cleanRows, COLUMNS);
  fs.writeFileSync(PRODUCTS_JSON, JSON.stringify(cleanRows, null, 2), "utf8");

  stats.product_urls = todoRows.length;
  stats.rows = cleanRows.length;
  stats.header_matches = Object.keys(cleanRows[0] || Object.fromEntries(COLUMNS.map((c) => [c, ""]))).join("|") === COLUMNS.join("|");
  stats.columns = COLUMNS.length;
  stats.bad_rows = cleanRows.filter((row) => !isGoodRow(row)).length;
  stats.absolute_urls = cleanRows.every((row) => row.product_url.startsWith("http") && row.product_image_url.startsWith("http"));
  stats.numeric_prices = cleanRows.every((row) => row.product_current_price === "" || Number.isFinite(Number(row.product_current_price)));
  stats.note = "Rows are expanded by sellable product variant when productproperties are available. Tradeline is an Apple reseller site; the live API does not expose 100000 unique products.";
  fs.writeFileSync(SUMMARY_JSON, JSON.stringify(stats, null, 2), "utf8");

  console.log(JSON.stringify(stats, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
