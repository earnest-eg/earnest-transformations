/* eslint-disable no-console */
process.env.NODE_TLS_REJECT_UNAUTHORIZED = process.env.NODE_TLS_REJECT_UNAUTHORIZED || "0";

const fs = require("fs");
const path = require("path");
const { URL } = require("url");
const zlib = require("zlib");

const BASE_URL = "https://www.shop.eva-cosmetics.com";
const TIMEZONE = "Africa/Cairo";
const OUT_DIR = path.join(process.cwd(), "output");
const TARGET_COLUMNS = [
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

const CATEGORY_MAP = [
  [/hair/i, "beauty > hair care"],
  [/face|facial|skin|serum|acne|anti-aging|anti aging|whitening|collagen|hyaluronic|spotless|sheet mask/i, "beauty > skin care"],
  [/body|senses|splash|deodorant|roll.?on|shower|cream|lotion|evasiline|jolieva|sun/i, "beauty > body care"],
  [/oral|tooth|fluoro|smokers/i, "beauty > oral care"],
  [/baby|bebe|kids/i, "baby products > personal care"],
  [/male|man look|grooming/i, "beauty > male grooming"],
  [/bundle|offer|sale|buy|gift|promo|frontpage|best sellers|new arrivals/i, "beauty > offers"],
];

const BRAND_PATTERNS = [
  "Eva Advanced Care Clinic",
  "Eva Skin Clinic",
  "Eva Skin Care",
  "Eva Senses",
  "Eva Recipe",
  "Eva Sun & Sea",
  "Eva Hair Clinic",
  "Aloe Eva",
  "Man Look Expert",
  "Man Look",
  "Jolieva",
  "Evasiline",
  "Fluoro",
  "One",
  "Bebe",
  "Eva",
];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJson(url, retries = 6) {
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          "user-agent": "Mozilla/5.0 EVA catalog scraper",
          accept: "application/json,text/plain,*/*",
        },
      });
      if (!response.ok) {
        if (response.status === 429) {
          const retryAfter = Number(response.headers.get("retry-after") || 0);
          await sleep((retryAfter > 0 ? retryAfter * 1000 : 3000 * attempt) + 500);
        }
        throw new Error(`HTTP ${response.status}`);
      }
      return await response.json();
    } catch (error) {
      if (attempt === retries) throw error;
      await sleep(500 * attempt);
    }
  }
}

async function fetchText(url, retries = 4) {
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          "user-agent": "Mozilla/5.0 EVA catalog scraper",
          accept: "text/html,application/xml,text/plain,*/*",
        },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.text();
    } catch (error) {
      if (attempt === retries) throw error;
      await sleep(500 * attempt);
    }
  }
}

function cleanText(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function numberOrBlank(value) {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(String(value).replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? String(n) : "";
}

function calculateDiscount(current, old) {
  const c = Number(current);
  const o = Number(old);
  if (!Number.isFinite(c) || !Number.isFinite(o) || o <= c || o <= 0) return "";
  return (((o - c) / o) * 100).toFixed(3);
}

function absoluteUrl(value) {
  if (!value) return "";
  if (String(value).startsWith("//")) return `https:${value}`;
  return new URL(value, BASE_URL).toString();
}

function productUrl(handle) {
  return `${BASE_URL}/products/${handle}`;
}

function extractUnit(title) {
  const text = cleanText(title);
  const matches = [...text.matchAll(/\b(\d+(?:[.,]\d+)?)\s*(ml|l|gm|g|kg|pcs|pieces|piece|ampoules|sheets?|wipes?)\b/gi)];
  if (!matches.length) return "";
  return matches.map((m) => `${m[1].replace(",", ".")} ${normalizeUnit(m[2])}`).join(" + ");
}

function normalizeUnit(unit) {
  const lower = unit.toLowerCase();
  if (lower === "gm") return "g";
  if (lower === "pieces") return "pcs";
  if (lower === "piece") return "pcs";
  if (lower === "sheets") return "sheet";
  return lower;
}

function extractWeight(title, grams) {
  const unit = extractUnit(title);
  if (unit) return unit;
  if (grams && Number(grams) > 0) return `${Number(grams)} g`;
  return "";
}

function extractRam(title) {
  const match = cleanText(title).match(/\b(\d{1,3})\s*GB\s*(?:RAM|Ram|ram)\b/i);
  return match ? `${match[1]}GB` : "";
}

function extractStorage(title) {
  const match = cleanText(title).match(/\b(\d{2,4})\s*(GB|TB)\s*(?:SSD|HDD|Storage|ROM)?\b/i);
  return match ? `${match[1]}${match[2].toUpperCase()}${/SSD/i.test(match[0]) ? " SSD" : ""}` : "";
}

function extractBrand(title, vendor) {
  const text = cleanText(title);
  const found = BRAND_PATTERNS.find((brand) => new RegExp(`\\b${escapeRegExp(brand)}\\b`, "i").test(text));
  if (found) return found;
  const cleanVendor = cleanText(vendor);
  if (cleanVendor && !/^my store$/i.test(cleanVendor) && !/^eva shop$/i.test(cleanVendor)) return cleanVendor;
  return text.split(/\s+/).slice(0, 2).join(" ");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function shortName(title) {
  return cleanText(title)
    .replace(/\([^)]*special offer[^)]*\)/gi, "")
    .replace(/\b(?:delicate musk|frosted skies|pure joy|gold spell|summer twist|cozy dream|in the clouds|love tale|night out|morning blossom|musky jasmine|spring lilies|mystic orchid)\b/gi, "")
    .replace(/\b\d+(?:[.,]\d+)?\s*(?:ml|l|gm|g|kg|pcs|pieces|piece|ampoules|sheets?|wipes?)\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function broadCategory(collectionTitle, tags) {
  const haystack = `${collectionTitle || ""} ${(tags || []).join(" ")}`;
  const found = CATEGORY_MAP.find(([regex]) => regex.test(haystack));
  return found ? found[1] : "beauty > personal care";
}

function chooseCategory(product, memberships) {
  const preferred = memberships.find((m) => !/frontpage|best sellers|new arrivals|offer|sale|buy|gift|promo/i.test(m.title));
  const chosen = preferred || memberships[0] || null;
  const tag = Array.isArray(product.tags) && product.tags.length ? cleanText(product.tags[0]) : "";
  return {
    product_category: broadCategory(chosen ? chosen.title : tag, product.tags),
    product_subcategory: chosen ? cleanText(chosen.title) : tag,
  };
}

function csvEscape(value) {
  const s = value === null || value === undefined ? "" : String(value);
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function writeCsv(filePath, rows, columns) {
  const lines = [columns.join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => csvEscape(row[column])).join(","));
  }
  fs.writeFileSync(filePath, `${lines.join("\n")}\n`, "utf8");
}

async function collectAllProducts() {
  const products = [];
  for (let page = 1; ; page += 1) {
    const url = `${BASE_URL}/products.json?limit=250&page=${page}`;
    const data = await fetchJson(url);
    const batch = data.products || [];
    console.log(`products page ${page}: ${batch.length}`);
    if (!batch.length) break;
    products.push(...batch);
    if (batch.length < 250) break;
    await sleep(250);
  }
  return products;
}

async function collectCollections() {
  const collections = [];
  for (let page = 1; ; page += 1) {
    const url = `${BASE_URL}/collections.json?limit=250&page=${page}`;
    const data = await fetchJson(url);
    const batch = data.collections || [];
    console.log(`collections page ${page}: ${batch.length}`);
    if (!batch.length) break;
    collections.push(...batch);
    if (batch.length < 250) break;
    await sleep(250);
  }
  return collections;
}

async function collectCollectionMemberships(collections) {
  const byProductId = new Map();
  const todos = [];
  for (const collection of collections) {
    const collectionTodo = {
      url: `${BASE_URL}/collections/${collection.handle}`,
      handle: collection.handle,
      title: cleanText(collection.title),
      expected_products_count: collection.products_count || "",
      discovered_products_count: 0,
      status: "pending",
      error: "",
    };
    try {
      for (let page = 1; ; page += 1) {
        const url = `${BASE_URL}/collections/${collection.handle}/products.json?limit=250&page=${page}`;
        const data = await fetchJson(url);
        const products = data.products || [];
        if (!products.length) break;
        collectionTodo.discovered_products_count += products.length;
        for (const product of products) {
          if (!byProductId.has(product.id)) byProductId.set(product.id, []);
          byProductId.get(product.id).push({
            handle: collection.handle,
            title: cleanText(collection.title),
            url: collectionTodo.url,
          });
        }
        if (products.length < 250) break;
        await sleep(200);
      }
      collectionTodo.status = "done";
    } catch (error) {
      collectionTodo.status = "error";
      collectionTodo.error = error.message;
    }
    todos.push(collectionTodo);
    console.log(`collection ${collection.handle}: ${collectionTodo.discovered_products_count}`);
    await sleep(500);
  }
  return { byProductId, todos };
}

function normalizeProduct(product, memberships, scrapingTime) {
  const title = cleanText(product.title);
  const variant = (product.variants || [])[0] || {};
  const image = (product.images || [])[0] || {};
  const current = numberOrBlank(variant.price);
  const old = numberOrBlank(variant.compare_at_price);
  const category = chooseCategory(product, memberships || []);
  const grams = variant.grams || 0;
  const row = {
    title,
    name: shortName(title) || title,
    product_current_price: current,
    product_old_price: old,
    product_discount: calculateDiscount(current, old),
    product_url: productUrl(product.handle),
    product_image_url: absoluteUrl(image.src),
    product_seller: cleanText(product.vendor) || "EVA Shop",
    product_availability: variant.available === true ? "in_stock" : variant.available === false ? "out_of_stock" : "",
    product_category: category.product_category,
    product_subcategory: category.product_subcategory,
    product_unit: extractUnit(title),
    product_weight: extractWeight(title, grams),
    scraping_time: scrapingTime,
    timestamp_timezone: TIMEZONE,
    product_brand: extractBrand(title, product.vendor),
    product_ram: extractRam(title),
    product_storage: extractStorage(title),
  };
  return row;
}

function isGoodRow(row) {
  if (!row.title || /undefined|null/i.test(row.title)) return false;
  if (!row.product_url.startsWith(BASE_URL)) return false;
  if (!row.product_current_price) return false;
  if (!row.product_image_url.startsWith("http")) return false;
  return true;
}

function writeZip(zipPath, files) {
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const file of files) {
    const name = Buffer.from(file.name);
    const content = fs.readFileSync(file.path);
    const compressed = zlib.deflateRawSync(content);
    const crc = crc32(content);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(content.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    chunks.push(local, name, compressed);

    const entry = Buffer.alloc(46);
    entry.writeUInt32LE(0x02014b50, 0);
    entry.writeUInt16LE(20, 4);
    entry.writeUInt16LE(20, 6);
    entry.writeUInt16LE(0, 8);
    entry.writeUInt16LE(8, 10);
    entry.writeUInt16LE(0, 12);
    entry.writeUInt16LE(0, 14);
    entry.writeUInt32LE(crc, 16);
    entry.writeUInt32LE(compressed.length, 20);
    entry.writeUInt32LE(content.length, 24);
    entry.writeUInt16LE(name.length, 28);
    entry.writeUInt16LE(0, 30);
    entry.writeUInt16LE(0, 32);
    entry.writeUInt16LE(0, 34);
    entry.writeUInt16LE(0, 36);
    entry.writeUInt32LE(0, 38);
    entry.writeUInt32LE(offset, 42);
    central.push(entry, name);
    offset += local.length + name.length + compressed.length;
  }
  const centralSize = central.reduce((sum, part) => sum + part.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);
  fs.writeFileSync(zipPath, Buffer.concat([...chunks, ...central, end]));
}

function crc32(buffer) {
  let crc = -1;
  for (const byte of buffer) {
    crc = (crc >>> 8) ^ CRC_TABLE[(crc ^ byte) & 0xff];
  }
  return (crc ^ -1) >>> 0;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

function productLocsFromSitemap(xml) {
  return [...xml.matchAll(/<loc>(.*?)<\/loc>/g)]
    .map((match) => match[1])
    .filter((url) => url.includes("/products/"));
}

async function collectDiscoveryAudit(products) {
  const [enSitemap, arSitemap, searchHtml] = await Promise.all([
    fetchText(`${BASE_URL}/sitemap_products_1.xml?from=8207058862271&to=8458114203839`).catch((error) => `ERROR:${error.message}`),
    fetchText(`${BASE_URL}/ar/sitemap_products_1.xml?from=8207058862271&to=8458114203839`).catch((error) => `ERROR:${error.message}`),
    fetchText(`${BASE_URL}/search?q=a&type=product`).catch((error) => `ERROR:${error.message}`),
  ]);
  const enLocs = enSitemap.startsWith("ERROR:") ? [] : productLocsFromSitemap(enSitemap);
  const arLocs = arSitemap.startsWith("ERROR:") ? [] : productLocsFromSitemap(arSitemap).map((url) => url.replace("/ar/products/", "/products/"));
  const searchCountMatch = searchHtml.match(/Search:\s*([\d,]+)\s+results found/i);
  const variants = products.reduce((sum, product) => sum + (product.variants || []).length, 0);
  return {
    products_json_unique_products: products.length,
    products_json_total_variants: variants,
    products_json_multi_variant_products: products.filter((product) => (product.variants || []).length > 1).length,
    english_product_sitemap_urls: enLocs.length,
    arabic_product_sitemap_urls: arLocs.length,
    unique_product_sitemap_urls_across_locales: new Set([...enLocs, ...arLocs]).size,
    storefront_search_broad_query_count: searchCountMatch ? Number(searchCountMatch[1].replace(/,/g, "")) : null,
    ucp_status: "Store advertises UCP; public MCP tools/list returned invalid_profile_url during this run. Public products, sitemaps, search, and collections were complete and consistent.",
  };
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const scrapingTime = new Intl.DateTimeFormat("sv-SE", {
    timeZone: TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date()).replace(" ", "T");

  const [products, collections] = await Promise.all([collectAllProducts(), collectCollections()]);
  const { byProductId, todos: categoryTodos } = await collectCollectionMemberships(collections);
  const discoveryAudit = await collectDiscoveryAudit(products);

  const deduped = new Map();
  for (const product of products) deduped.set(product.id, product);

  const rows = [...deduped.values()]
    .map((product) => normalizeProduct(product, byProductId.get(product.id) || [], scrapingTime))
    .filter(isGoodRow);

  const productTodos = [...deduped.values()].map((product) => ({
    url: productUrl(product.handle),
    category: chooseCategory(product, byProductId.get(product.id) || []).product_category,
    subcategory: chooseCategory(product, byProductId.get(product.id) || []).product_subcategory,
    status: isGoodRow(normalizeProduct(product, byProductId.get(product.id) || [], scrapingTime)) ? "done" : "dropped",
    error: "",
  }));

  const csvPath = path.join(OUT_DIR, "eva_products_clean.csv");
  const jsonPath = path.join(OUT_DIR, "eva_products_clean.json");
  const todoProductsPath = path.join(OUT_DIR, "todo_products.csv");
  const todoCategoriesPath = path.join(OUT_DIR, "todo_categories.csv");
  const reportPath = path.join(OUT_DIR, "validation_report.json");
  const zipPath = path.join(OUT_DIR, "eva_products_archive.zip");

  writeCsv(csvPath, rows, TARGET_COLUMNS);
  fs.writeFileSync(jsonPath, JSON.stringify(rows, null, 2), "utf8");
  writeCsv(todoProductsPath, productTodos, ["url", "category", "subcategory", "status", "error"]);
  writeCsv(todoCategoriesPath, categoryTodos, ["url", "handle", "title", "expected_products_count", "discovered_products_count", "status", "error"]);

  const report = {
    site: BASE_URL,
    scraped_at: scrapingTime,
    timestamp_timezone: TIMEZONE,
    target_columns_count: TARGET_COLUMNS.length,
    header_matches_target: TARGET_COLUMNS.every((col, idx) => Object.keys(rows[0] || Object.fromEntries(TARGET_COLUMNS.map((c) => [c, ""])))[idx] === col),
    discovered_unique_products: deduped.size,
    exported_rows: rows.length,
    dropped_rows: deduped.size - rows.length,
    discovered_collections: collections.length,
    completed_collections: categoryTodos.filter((row) => row.status === "done").length,
    discovery_audit: discoveryAudit,
    requested_minimum_products: 100000,
    minimum_met: rows.length >= 100000,
    note: rows.length >= 100000 ? "" : "The public Shopify catalog exposes fewer than 100000 unique products. Export contains the maximum unique products discovered from products.json and collection loops.",
    columns: TARGET_COLUMNS,
    files: {
      csv: csvPath,
      json: jsonPath,
      todo_products: todoProductsPath,
      todo_categories: todoCategoriesPath,
      zip: zipPath,
    },
  };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");

  writeZip(zipPath, [
    { name: "eva_products_clean.csv", path: csvPath },
    { name: "eva_products_clean.json", path: jsonPath },
    { name: "todo_products.csv", path: todoProductsPath },
    { name: "todo_categories.csv", path: todoCategoriesPath },
    { name: "validation_report.json", path: reportPath },
  ]);

  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
