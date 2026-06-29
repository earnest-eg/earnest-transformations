const fs = require("fs");
const path = require("path");
const { URL } = require("url");
const zlib = require("zlib");

process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

const BASE_URL = "https://ennap.com";
const TIMEZONE = "Africa/Cairo";
const SELLER = "Ennap.com";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36";

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

const MARKETING_COLLECTIONS = new Set([
  "all", "best-sellers", "new-releases", "newly-restocked", "featured", "top-deals",
  "deal-of-the-day", "under-500", "under-1000", "under-5000", "last-piece",
  "exclusive-products", "pre-order",
]);

const CATEGORY_RULES = [
  [/(iphone|android|smart phones|mobile phones|phones|huawei mobiles|gaming phones)/i, "electronics > mobiles"],
  [/(mobile accessories|mobile cases|screen protectors|mobile cables|chargers|power adapters|power banks)/i, "electronics > mobile accessories"],
  [/(laptop|macbook|computers|desktops|monitors|computer)/i, "electronics > computers"],
  [/(tablet|ipad|galaxy tab)/i, "electronics > tablets"],
  [/(headphone|earbuds|airpods|audio|speaker|microphone|neckband)/i, "electronics > audio"],
  [/(watch|watches|wearable|fitness tracker|smart ring)/i, "electronics > wearables"],
  [/(gaming|playstation|nintendo|vr|controller)/i, "electronics > gaming"],
  [/(camera|tripod|selfie|recorder)/i, "electronics > cameras"],
  [/(appliances|air fryer|kitchen|coffee|robot vacuum|blender)/i, "home > appliances"],
  [/(bags|luggage|wallet|backpack)/i, "fashion > bags"],
  [/(security|smart home|streaming|lighting)/i, "electronics > smart home"],
  [/(scooter)/i, "sports > scooters"],
];

const BRAND_HINTS = [
  "Apple", "Samsung", "Xiaomi", "Redmi", "Honor", "Huawei", "OnePlus", "Oppo",
  "Lenovo", "Dell", "HP", "Asus", "Acer", "JBL", "Sony", "Anker", "Baseus",
  "Nillkin", "WiWU", "Nintendo", "PlayStation", "Powerology", "Green Lion",
  "Skinarma", "Nothing", "Amazfit", "Jabra", "Mpow", "IQibla", "DOBE",
];

function argValue(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const OUTPUT_DIR = argValue("--output-dir", "output");
const PAGE_LIMIT = argValue("--page-limit") ? Number(argValue("--page-limit")) : null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchText(url, retries = 6) {
  let lastError = null;
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = await fetch(url, { headers: { "user-agent": USER_AGENT } });
      if (response.status === 429 && attempt < retries) {
        const retryAfter = Number(response.headers.get("retry-after") || 0);
        await sleep((retryAfter > 0 ? retryAfter * 1000 : 5000 * attempt));
        continue;
      }
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.text();
    } catch (error) {
      lastError = error;
      if (attempt < retries) await sleep(700 * attempt);
    }
  }
  throw new Error(`failed to fetch ${url}: ${lastError.message}`);
}

async function fetchJson(url) {
  return JSON.parse(await fetchText(url));
}

function decodeEntities(text) {
  return String(text ?? "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ");
}

function cleanText(value) {
  return decodeEntities(value)
    .replace(/<[^>]+>/g, " ")
    .replace(/[\u200b-\u200f\u202a-\u202e]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function numericPrice(value) {
  if (value === null || value === undefined || value === "") return "";
  const match = String(value).match(/\d+(?:[,\d]*)(?:\.\d+)?/);
  if (!match) return "";
  const number = Number(match[0].replace(/,/g, ""));
  return Number.isInteger(number) ? String(number) : String(number).replace(/0+$/, "").replace(/\.$/, "");
}

function calculateDiscount(current, old) {
  if (!current || !old) return "";
  const currentValue = Number(current);
  const oldValue = Number(old);
  if (!(oldValue > currentValue)) return "";
  return (((oldValue - currentValue) / oldValue) * 100).toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function absoluteUrl(url) {
  if (!url) return "";
  if (url.startsWith("//")) return `https:${url}`;
  return new URL(url, BASE_URL).toString();
}

function parseLocs(xml) {
  return [...xml.matchAll(/<loc>([\s\S]*?)<\/loc>/g)].map((match) => decodeEntities(match[1].trim()));
}

function parseProductImagesFromSitemap(xml) {
  const imageByProduct = new Map();
  for (const block of xml.matchAll(/<url>([\s\S]*?)<\/url>/g)) {
    const loc = block[1].match(/<loc>([\s\S]*?)<\/loc>/);
    const image = block[1].match(/<image:loc>([\s\S]*?)<\/image:loc>/);
    if (loc && image && loc[1].includes("/products/")) {
      imageByProduct.set(decodeEntities(loc[1].trim()), decodeEntities(image[1].trim()));
    }
  }
  return imageByProduct;
}

async function discoverSitemapUrls() {
  const parent = await fetchText(`${BASE_URL}/sitemap.xml`);
  const sitemapUrls = parseLocs(parent);
  const productUrls = new Set();
  const collectionUrls = new Set();
  const imageByProduct = new Map();

  for (const sitemapUrl of sitemapUrls) {
    if (sitemapUrl.includes("/ar/")) continue;
    if (!sitemapUrl.includes("sitemap_products") && !sitemapUrl.includes("sitemap_collections")) continue;
    const xml = await fetchText(sitemapUrl);
    for (const loc of parseLocs(xml)) {
      if (loc.includes("/products/")) productUrls.add(loc);
      if (loc.includes("/collections/")) collectionUrls.add(loc);
    }
    if (sitemapUrl.includes("sitemap_products")) {
      for (const [productUrl, imageUrl] of parseProductImagesFromSitemap(xml)) {
        imageByProduct.set(productUrl, imageUrl);
      }
    }
  }
  return { productUrls, collectionUrls, imageByProduct };
}

async function fetchPaginated(endpoint, key) {
  const items = [];
  for (let page = 1; ; page++) {
    if (PAGE_LIMIT && page > PAGE_LIMIT) break;
    const separator = endpoint.includes("?") ? "&" : "?";
    const payload = await fetchJson(`${endpoint}${separator}limit=250&page=${page}`);
    const chunk = payload[key] || [];
    if (!chunk.length) break;
    items.push(...chunk);
    console.log(`${key}: page ${page}, got ${chunk.length}, total ${items.length}`);
    if (chunk.length < 250) break;
    await sleep(500);
  }
  return items;
}

async function discoverCollections() {
  let collections = [];
  try {
    collections = await fetchPaginated(`${BASE_URL}/collections.json`, "collections");
  } catch (error) {
    console.log(`collection discovery failed, continuing with product fallback: ${error.message}`);
  }
  const byHandle = new Map();
  for (const collection of collections) byHandle.set(collection.handle || "", collection);
  return byHandle;
}

async function discoverCollectionMemberships(collections) {
  const productCollections = new Map();
  const sorted = [...collections.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [handle, collection] of sorted) {
    if (!handle || !(collection.products_count > 0)) continue;
    try {
      const products = await fetchPaginated(`${BASE_URL}/collections/${encodeURIComponent(handle)}/products.json`, "products");
      for (const product of products) {
        if (!productCollections.has(product.handle)) productCollections.set(product.handle, []);
        productCollections.get(product.handle).push({
          handle,
          title: cleanText(collection.title),
          products_count: collection.products_count || 0,
        });
      }
    } catch (error) {
      console.log(`collection failed: ${handle}: ${error.message}`);
    }
    await sleep(650);
  }
  return productCollections;
}

function chooseCollection(product, memberships) {
  let usable = memberships.filter((item) => !MARKETING_COLLECTIONS.has(item.handle));
  if (!usable.length) usable = memberships.slice();
  if (usable.length) {
    usable.sort((a, b) => (a.products_count - b.products_count) || String(a.title).length - String(b.title).length);
    return usable[0].title || "";
  }
  return cleanText(product.product_type);
}

function standardCategory(product, subcategory) {
  const haystack = [
    subcategory,
    cleanText(product.product_type),
    ...(product.tags || []).map(cleanText),
    cleanText(product.title),
  ].join(" ");
  for (const [pattern, category] of CATEGORY_RULES) {
    if (pattern.test(haystack)) return category;
  }
  return "electronics";
}

function extractRam(text) {
  let match = text.match(/(?<!\d)(\d{1,3})\s*(?:GB|G)\s*(?:RAM|Unified Memory|DDR\d*)/i);
  if (match) return `${match[1]}GB`;
  match = text.match(/(?:RAM|Memory)\s*[:\-]?\s*(\d{1,3})\s*(?:GB|G)/i);
  return match ? `${match[1]}GB` : "";
}

function extractStorage(text) {
  const patterns = [
    /(?<!\d)(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:SSD|HDD|Storage|ROM)/i,
    /(?:Storage Capacity|Storage|ROM)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(TB|GB)/i,
    /(\d+(?:\.\d+)?)\s*(TB|GB)\s*\+\s*\d+\s*GB/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) {
      const amount = match[1].replace(/\.0$/, "");
      const suffix = /SSD/i.test(match[0]) ? " SSD" : "";
      return `${amount}${match[2].toUpperCase()}${suffix}`;
    }
  }
  return "";
}

function extractUnit(text) {
  let match = text.match(/(?<!\d)(\d+(?:\.\d+)?)\s*(pcs|pieces|pack|packs|m|cm|mm|inch|inches|w|mah)\b/i);
  if (match) return `${match[1]} ${match[2].toLowerCase()}`;
  match = text.match(/(\d+)\s*-\s*pack\b/i);
  return match ? `${match[1]} pack` : "";
}

function extractWeight(text, grams) {
  if (grams) return grams >= 1000 ? `${Number(grams / 1000).toString()} kg` : `${grams} g`;
  const match = text.match(/(?<!\d)(\d+(?:\.\d+)?)\s*(kg|g|gram|grams|ml|l|liter|litre)\b/i);
  if (!match) return "";
  const unit = { gram: "g", grams: "g", liter: "l", litre: "l" }[match[2].toLowerCase()] || match[2].toLowerCase();
  return `${match[1]} ${unit}`;
}

function inferBrand(product, text) {
  const vendor = cleanText(product.vendor);
  if (vendor) return vendor;
  for (const brand of BRAND_HINTS) {
    if (new RegExp(`\\b${brand.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(text)) return brand;
  }
  return "";
}

function variantTitle(productTitle, variantTitleValue) {
  const variant = cleanText(variantTitleValue);
  if (!variant || variant.toLowerCase() === "default title") return productTitle;
  return `${productTitle} - ${variant}`;
}

function shortName(title) {
  return title
    .split(/\s+-\s+/, 1)[0]
    .replace(/\b(Color|Colour|Storage Capacity|Size|Package|Keyboard Language):.*$/i, "")
    .replace(/\s{2,}/g, " ")
    .replace(/[\s-]+$/g, "");
}

function makeRows(products, productCollections, sitemapImages) {
  const rows = [];
  const scrapeTime = new Date().toISOString();
  for (const product of products) {
    const baseTitle = cleanText(product.title);
    const handle = product.handle || "";
    if (!baseTitle || !handle) continue;
    const memberships = productCollections.get(handle) || [];
    const subcategory = chooseCollection(product, memberships);
    const category = standardCategory(product, subcategory);
    const bodyText = cleanText(product.body_html);
    const productUrl = `${BASE_URL}/products/${handle}`;
    const images = product.images || [];
    const fallbackImage = images[0]?.src ? absoluteUrl(images[0].src) : (sitemapImages.get(productUrl) || "");
    for (const variant of product.variants || [{}]) {
      const title = variantTitle(baseTitle, variant.title);
      const variantValues = Object.values(variant).filter((value) => typeof value === "string").map(cleanText).join(" ");
      const fullText = `${title} ${bodyText} ${variantValues}`;
      const currentPrice = numericPrice(variant.price);
      const oldPrice = numericPrice(variant.compare_at_price);
      const imageUrl = variant.featured_image?.src ? absoluteUrl(variant.featured_image.src) : fallbackImage;
      if (!currentPrice || !imageUrl) continue;
      rows.push({
        title,
        name: shortName(baseTitle),
        product_current_price: currentPrice,
        product_old_price: oldPrice,
        product_discount: calculateDiscount(currentPrice, oldPrice),
        product_url: variant.id ? `${productUrl}?variant=${variant.id}` : productUrl,
        product_image_url: imageUrl,
        product_seller: SELLER,
        product_availability: variant.available ? "in_stock" : "out_of_stock",
        product_category: category,
        product_subcategory: subcategory,
        product_unit: extractUnit(fullText),
        product_weight: extractWeight(fullText, variant.grams),
        scraping_time: scrapeTime,
        timestamp_timezone: TIMEZONE,
        product_brand: inferBrand(product, fullText),
        product_ram: extractRam(fullText),
        product_storage: extractStorage(fullText),
      });
    }
  }
  return rows;
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function writeCsv(filePath, rows, columns) {
  const lines = [columns.join(",")];
  for (const row of rows) lines.push(columns.map((column) => csvEscape(row[column])).join(","));
  fs.writeFileSync(filePath, `\uFEFF${lines.join("\n")}`, "utf8");
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2), "utf8");
}

function writeTodo(filePath, productUrls, productCollections) {
  const rows = [...productUrls].sort().map((url) => {
    const handle = url.replace(/\/$/, "").split("/").pop();
    const memberships = productCollections.get(handle) || [];
    return {
      url,
      category: memberships.map((item) => item.title || "").join("|"),
      status: "pending",
      error: "",
    };
  });
  writeCsv(filePath, rows, ["url", "category", "status", "error"]);
}

function validate(rows) {
  const errors = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    if (Object.keys(row).length !== TARGET_COLUMNS.length) errors.push(`row ${i + 2}: column mismatch`);
    if (!row.title || ["undefined", "null"].includes(row.title.toLowerCase())) errors.push(`row ${i + 2}: bad title`);
    if (!row.product_url.startsWith("https://")) errors.push(`row ${i + 2}: product_url is not absolute`);
    if (!row.product_image_url.startsWith("https://")) errors.push(`row ${i + 2}: product_image_url is not absolute`);
    if (row.product_current_price && !/^\d+(?:\.\d+)?$/.test(row.product_current_price)) errors.push(`row ${i + 2}: current price is not numeric`);
    if (row.product_old_price && !/^\d+(?:\.\d+)?$/.test(row.product_old_price)) errors.push(`row ${i + 2}: old price is not numeric`);
    if (row.timestamp_timezone !== TIMEZONE) errors.push(`row ${i + 2}: timezone mismatch`);
    if (errors.length > 20) break;
  }
  return {
    header: TARGET_COLUMNS,
    column_count: TARGET_COLUMNS.length,
    row_count: rows.length,
    unique_product_urls: new Set(rows.map((row) => row.product_url.split("?variant=")[0])).size,
    errors,
  };
}

function crc32(buffer) {
  let table = crc32.table;
  if (!table) {
    table = crc32.table = Array.from({ length: 256 }, (_, n) => {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      return c >>> 0;
    });
  }
  let crc = -1;
  for (const byte of buffer) crc = (crc >>> 8) ^ table[(crc ^ byte) & 0xff];
  return (crc ^ -1) >>> 0;
}

function dosTimeDate(date) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const day = date.getDate();
  const month = date.getMonth() + 1;
  const year = Math.max(date.getFullYear() - 1980, 0);
  return { time, date: (year << 9) | (month << 5) | day };
}

function writeUInt32(buffer, value, offset) {
  buffer.writeUInt32LE(value >>> 0, offset);
}

function createZip(zipPath, files) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  const now = dosTimeDate(new Date());
  for (const filePath of files) {
    const name = Buffer.from(path.basename(filePath));
    const data = fs.readFileSync(filePath);
    const compressed = zlib.deflateRawSync(data);
    const crc = crc32(data);

    const local = Buffer.alloc(30 + name.length);
    writeUInt32(local, 0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(now.time, 10);
    local.writeUInt16LE(now.date, 12);
    writeUInt32(local, crc, 14);
    writeUInt32(local, compressed.length, 18);
    writeUInt32(local, data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    name.copy(local, 30);
    localParts.push(local, compressed);

    const central = Buffer.alloc(46 + name.length);
    writeUInt32(central, 0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(now.time, 12);
    central.writeUInt16LE(now.date, 14);
    writeUInt32(central, crc, 16);
    writeUInt32(central, compressed.length, 20);
    writeUInt32(central, data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    writeUInt32(central, 0, 38);
    writeUInt32(central, offset, 42);
    name.copy(central, 46);
    centralParts.push(central);
    offset += local.length + compressed.length;
  }
  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
  const end = Buffer.alloc(22);
  writeUInt32(end, 0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  writeUInt32(end, centralSize, 12);
  writeUInt32(end, offset, 16);
  end.writeUInt16LE(0, 20);
  fs.writeFileSync(zipPath, Buffer.concat([...localParts, ...centralParts, end]));
}

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  console.log("Discovering sitemap product and collection URLs...");
  const { productUrls: sitemapProductUrls, imageByProduct } = await discoverSitemapUrls();
  console.log(`Sitemap product URLs: ${sitemapProductUrls.size}`);

  console.log("Discovering collections...");
  const collections = await discoverCollections();
  console.log(`Collections: ${collections.size}`);

  console.log("Looping collections to build product-category todo data...");
  const productCollections = await discoverCollectionMemberships(collections);
  const collectionProductUrls = new Set([...productCollections.keys()].map((handle) => `${BASE_URL}/products/${handle}`));
  const allProductUrls = new Set([...sitemapProductUrls, ...collectionProductUrls]);

  const todoPath = path.join(OUTPUT_DIR, "todo_products.csv");
  writeTodo(todoPath, allProductUrls, productCollections);
  console.log(`Wrote todo: ${todoPath} (${allProductUrls.size} product URLs)`);

  console.log("Fetching full product JSON pages...");
  const products = await fetchPaginated(`${BASE_URL}/products.json`, "products");
  const byHandle = new Map(products.filter((product) => product.handle).map((product) => [product.handle, product]));

  const missing = [...allProductUrls].filter((url) => !byHandle.has(url.replace(/\/$/, "").split("/").pop()));
  if (missing.length) console.log(`Warning: ${missing.length} sitemap products were not returned by products.json`);

  console.log("Normalizing, enriching, and validating rows...");
  const rows = makeRows([...byHandle.values()], productCollections, imageByProduct);
  const validation = validate(rows);

  const csvPath = path.join(OUTPUT_DIR, "ennap_products_clean.csv");
  const jsonPath = path.join(OUTPUT_DIR, "ennap_products_clean.json");
  const validationPath = path.join(OUTPUT_DIR, "validation_report.json");
  const zipPath = path.join(OUTPUT_DIR, "ennap_exports.zip");
  writeCsv(csvPath, rows, TARGET_COLUMNS);
  writeJson(jsonPath, rows);
  writeJson(validationPath, validation);
  createZip(zipPath, [todoPath, csvPath, jsonPath, validationPath]);

  console.log(JSON.stringify(validation, null, 2));
  console.log(`Wrote CSV: ${csvPath}`);
  console.log(`Wrote JSON: ${jsonPath}`);
  console.log(`Wrote ZIP: ${zipPath}`);
  if (validation.unique_product_urls < 100000) {
    console.log("Note: the discovered Shopify catalog contains fewer than 100000 unique product URLs; exported the maximum available product/variant rows found from public endpoints.");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
