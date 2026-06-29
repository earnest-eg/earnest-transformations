const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const BASE = "https://www.compumarts.com";
const TZ = "Africa/Cairo";
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

const COLLECTION_HINTS = [
  ["laptop", "electronics > laptops"],
  ["notebook", "electronics > laptops"],
  ["monitor", "electronics > monitors"],
  ["graphics", "electronics > computer components"],
  ["gpu", "electronics > computer components"],
  ["processor", "electronics > computer components"],
  ["cpu", "electronics > computer components"],
  ["motherboard", "electronics > computer components"],
  ["ram", "electronics > computer components"],
  ["memory", "electronics > computer components"],
  ["ssd", "electronics > storage"],
  ["hdd", "electronics > storage"],
  ["storage", "electronics > storage"],
  ["case", "electronics > computer cases"],
  ["cooler", "electronics > cooling"],
  ["fan", "electronics > cooling"],
  ["psu", "electronics > power supplies"],
  ["power supply", "electronics > power supplies"],
  ["keyboard", "electronics > accessories"],
  ["mouse", "electronics > accessories"],
  ["mouses", "electronics > accessories"],
  ["mouse pad", "electronics > accessories"],
  ["headphone", "electronics > audio"],
  ["speaker", "electronics > audio"],
  ["microphone", "electronics > audio"],
  ["webcam", "electronics > accessories"],
  ["chair", "gaming > chairs"],
  ["controller", "gaming > accessories"],
  ["cable", "electronics > accessories"],
  ["adapter", "electronics > accessories"],
  ["pc bundle", "electronics > desktops"],
  ["bundle", "electronics > desktops"],
  ["desktop", "electronics > desktops"],
  ["all-in-one", "electronics > desktops"],
];

function ensureOutDir() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

function nowCairo() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const v = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${v.year}-${v.month}-${v.day} ${v.hour}:${v.minute}:${v.second}`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchText(url, accept = "text/html") {
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      return execFileSync(
        "curl.exe",
        [
          "-sS",
          "-L",
          "--ssl-no-revoke",
          "--max-time",
          "30",
          "-A",
          "Mozilla/5.0 (compatible; CompumartsDataScraper/1.0)",
          "-H",
          `Accept: ${accept}`,
          url,
        ],
        { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 }
      );
    } catch (error) {
      if (attempt === 3) throw new Error(`${url}: ${error.message}`);
      await sleep(750 * attempt);
    }
  }
  return "";
}

async function fetchJson(url) {
  const text = await fetchText(url, "application/json,text/plain,*/*");
  return JSON.parse(text);
}

function cleanText(value) {
  if (value == null) return "";
  return String(value)
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/[^\x20-\x7E]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function csvEscape(value) {
  const s = value == null ? "" : String(value);
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function writeCsv(file, rows, columns) {
  const lines = [columns.join(",")];
  for (const row of rows) {
    lines.push(columns.map((col) => csvEscape(row[col])).join(","));
  }
  fs.writeFileSync(file, lines.join("\n") + "\n", "utf8");
}

function parseLocs(xml) {
  return [...xml.matchAll(/<loc>\s*([^<]+?)\s*<\/loc>/gi)].map((m) =>
    m[1].replace(/&amp;/g, "&").trim()
  );
}

function collectionHandleFromUrl(url) {
  const match = url.match(/\/collections\/([^/?#]+)/i);
  return match ? decodeURIComponent(match[1]) : "";
}

function productHandleFromUrl(url) {
  const match = url.match(/\/products\/([^/?#]+)/i);
  return match ? decodeURIComponent(match[1]) : "";
}

function titleFromHandle(handle) {
  return cleanText(handle.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()));
}

function numericPrice(value) {
  if (value == null || value === "") return "";
  const n = Number(String(value).replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? String(Math.round(n * 100) / 100).replace(/\.00$/, "") : "";
}

function discountPercent(current, oldPrice) {
  const currentNum = Number(current);
  const oldNum = Number(oldPrice);
  if (!oldNum || !currentNum || oldNum <= currentNum) return "";
  return String(Math.round(((oldNum - currentNum) / oldNum) * 100000) / 1000);
}

function absoluteUrl(url) {
  if (!url) return "";
  if (url.startsWith("//")) return `https:${url}`;
  if (/^https?:\/\//i.test(url)) return url;
  return new URL(url, BASE).toString();
}

function bestImage(product, variant) {
  if (variant?.featured_image?.src) return absoluteUrl(variant.featured_image.src);
  if (Array.isArray(product.images) && product.images[0]?.src) return absoluteUrl(product.images[0].src);
  return "";
}

function standardCategory(productType, collectionNames) {
  const haystack = [productType, ...collectionNames].join(" ").toLowerCase();
  for (const [needle, category] of COLLECTION_HINTS) {
    if (haystack.includes(needle)) return category;
  }
  return "electronics";
}

function extractRam(text) {
  const patterns = [
    /\b(\d{1,3}\s?(?:GB|G)\s?(?:DDR[345]|RAM|Memory))\b/i,
    /\b(?:RAM|Memory)\s*[:\-]?\s*(\d{1,3}\s?(?:GB|G))\b/i,
    /\b(\d{1,3}\s?GB)\s+RAM\b/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].replace(/\s+/g, " ").toUpperCase();
  }
  return "";
}

function extractStorage(text) {
  const patterns = [
    /\b(\d+(?:\.\d+)?\s?(?:TB|GB)\s?(?:NVME|M\.2|SSD|HDD|EMMC))\b/i,
    /\b((?:NVME|M\.2|SSD|HDD|EMMC)\s*\d+(?:\.\d+)?\s?(?:TB|GB))\b/i,
    /\b(?:Storage|Capacity)\s*[:\-]?\s*(\d+(?:\.\d+)?\s?(?:TB|GB))\b/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].replace(/\s+/g, " ").toUpperCase();
  }
  return "";
}

function extractUnit(text) {
  const patterns = [
    /\b(\d+\s?(?:pcs|pieces|pack|keys|fans|mm|inch|inches))\b/i,
    /\b(\d+(?:\.\d+)?\s+(?:ml|l|g|kg))\b/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].replace(/\s+/g, " ");
  }
  return "";
}

function extractWeight(product, variant, text) {
  if (variant?.grams && Number(variant.grams) > 0) return `${variant.grams} g`;
  const match = text.match(/\b(\d+(?:\.\d+)?\s+(?:kg|g|gram|grams))\b/i);
  return match ? match[1].replace(/\s+/g, " ") : "";
}

function shortName(title, brand) {
  let s = cleanText(title);
  if (brand && s.toLowerCase().startsWith(`${brand.toLowerCase()} `)) {
    s = s.slice(brand.length).trim();
  }
  s = s
    .replace(/\b(black|white|silver|gray|grey|red|blue|green|pink|orange|gold)\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
  const cut = s.search(/\s(?:with|for|featuring| - | \| |,)/i);
  if (cut > 25) s = s.slice(0, cut).trim();
  return s || cleanText(title);
}

function availability(product, variant) {
  const tags = Array.isArray(product.tags) ? product.tags.join(" ").toLowerCase() : "";
  if (tags.includes("out-of-stock") || tags.includes("out of stock")) return "out_of_stock";
  return variant?.available ? "in_stock" : "out_of_stock";
}

function productUrl(product, variant) {
  const url = `${BASE}/products/${product.handle}`;
  return variant?.id ? `${url}?variant=${variant.id}` : url;
}

async function discoverSitemapsAndCollections() {
  const sitemapXml = await fetchText(`${BASE}/sitemap.xml`, "application/xml,text/xml,*/*");
  const sitemapLocs = parseLocs(sitemapXml);
  const todoCollections = new Map();
  const todoProducts = new Map();

  for (const sitemapUrl of sitemapLocs) {
    try {
      const xml = await fetchText(sitemapUrl, "application/xml,text/xml,*/*");
      for (const loc of parseLocs(xml)) {
        const collectionHandle = collectionHandleFromUrl(loc);
        const productHandle = productHandleFromUrl(loc);
        if (collectionHandle) {
          todoCollections.set(collectionHandle, {
            url: `${BASE}/collections/${collectionHandle}`,
            title: titleFromHandle(collectionHandle),
          });
        }
        if (productHandle) {
          todoProducts.set(productHandle, {
            product_url: `${BASE}/products/${productHandle}`,
            category: "",
            status: "pending",
            error: "",
          });
        }
      }
    } catch (error) {
      console.error(`sitemap failed ${sitemapUrl}: ${error.message}`);
    }
  }

  return { todoCollections, todoProducts };
}

async function fetchCollectionProducts(handle) {
  const products = [];
  for (let page = 1; page <= 400; page++) {
    const url = `${BASE}/collections/${encodeURIComponent(handle)}/products.json?limit=250&page=${page}`;
    const json = await fetchJson(url);
    const chunk = Array.isArray(json.products) ? json.products : [];
    if (chunk.length === 0) break;
    products.push(...chunk);
    if (chunk.length < 250) break;
    await sleep(200);
  }
  return products;
}

async function fetchAllProductsFeed() {
  const products = [];
  for (let page = 1; page <= 1000; page++) {
    const url = `${BASE}/products.json?limit=250&page=${page}`;
    const json = await fetchJson(url);
    const chunk = Array.isArray(json.products) ? json.products : [];
    if (chunk.length === 0) break;
    products.push(...chunk);
    console.log(`products.json page ${page}: ${chunk.length}`);
    if (chunk.length < 250) break;
    await sleep(250);
  }
  return products;
}

function mergeProduct(map, product, collectionTitle) {
  const existing = map.get(product.handle);
  if (!existing) {
    map.set(product.handle, { product, collections: new Set(collectionTitle ? [collectionTitle] : []) });
    return;
  }
  if (collectionTitle) existing.collections.add(collectionTitle);
  existing.product = { ...existing.product, ...product };
}

function buildRows(productMap) {
  const scrapeTime = nowCairo();
  const rows = [];
  for (const { product, collections } of productMap.values()) {
    const collectionNames = [...collections].filter(Boolean);
    const productType = cleanText(product.product_type);
    const subcategory = collectionNames[0] || productType;
    const brand = cleanText(product.vendor);
    const baseText = cleanText(
      [product.title, productType, brand, product.tags?.join(" "), product.body_html].join(" ")
    );
    const variants = Array.isArray(product.variants) && product.variants.length ? product.variants : [{}];
    for (const variant of variants) {
      const variantTitle = cleanText(variant.title);
      const isDefault = !variantTitle || variantTitle.toLowerCase() === "default title";
      const title = cleanText(isDefault ? product.title : `${product.title} - ${variantTitle}`);
      const current = numericPrice(variant.price);
      const oldPrice = numericPrice(variant.compare_at_price);
      const image = bestImage(product, variant);
      const url = productUrl(product, variant);
      const text = `${baseText} ${variantTitle} ${variant.sku || ""}`;
      const row = {
        title,
        name: shortName(title, brand),
        product_current_price: current,
        product_old_price: oldPrice,
        product_discount: discountPercent(current, oldPrice),
        product_url: url,
        product_image_url: image,
        product_seller: "Compumarts Egypt",
        product_availability: availability(product, variant),
        product_category: standardCategory(productType, collectionNames),
        product_subcategory: subcategory,
        product_unit: extractUnit(text),
        product_weight: extractWeight(product, variant, text),
        scraping_time: scrapeTime,
        timestamp_timezone: TZ,
        product_brand: brand,
        product_ram: extractRam(text),
        product_storage: extractStorage(text),
      };
      if (
        row.title &&
        row.product_url &&
        row.product_current_price &&
        Number(row.product_current_price) > 0 &&
        row.product_image_url
      ) {
        rows.push(row);
      }
    }
  }
  return rows;
}

function validateRows(rows) {
  const problems = [];
  for (const [index, row] of rows.entries()) {
    if (Object.keys(row).length !== TARGET_COLUMNS.length) problems.push(`row ${index + 1}: bad column count`);
    if (!/^https?:\/\//.test(row.product_url)) problems.push(`row ${index + 1}: product_url not absolute`);
    if (row.product_image_url && !/^https?:\/\//.test(row.product_image_url)) {
      problems.push(`row ${index + 1}: image_url not absolute`);
    }
    if (row.product_current_price && !/^\d+(\.\d+)?$/.test(row.product_current_price)) {
      problems.push(`row ${index + 1}: current price not numeric`);
    }
    if (row.product_old_price && !/^\d+(\.\d+)?$/.test(row.product_old_price)) {
      problems.push(`row ${index + 1}: old price not numeric`);
    }
  }
  return problems;
}

function zipOutputs(files) {
  const zipPath = path.join(OUT_DIR, "compumarts_scrape_outputs.zip");
  if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
  try {
    execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        `Compress-Archive -Path ${files.map((f) => `'${f.replace(/'/g, "''")}'`).join(",")} -DestinationPath '${zipPath.replace(/'/g, "''")}' -Force`,
      ],
      { stdio: "inherit" }
    );
  } catch (error) {
    console.error(`zip failed: ${error.message}`);
  }
  return zipPath;
}

async function main() {
  ensureOutDir();
  console.log("Discovering sitemap URLs and collections...");
  const { todoCollections, todoProducts } = await discoverSitemapsAndCollections();
  console.log(`Discovered ${todoCollections.size} collections and ${todoProducts.size} product URLs from sitemap.`);

  const productMap = new Map();
  const todoRows = [...todoProducts.values()];

  for (const [handle, collection] of todoCollections.entries()) {
    try {
      const products = await fetchCollectionProducts(handle);
      console.log(`collection ${handle}: ${products.length}`);
      for (const product of products) {
        mergeProduct(productMap, product, collection.title);
        const url = `${BASE}/products/${product.handle}`;
        if (!todoProducts.has(product.handle)) {
          todoProducts.set(product.handle, {
            product_url: url,
            category: collection.title,
            status: "pending",
            error: "",
          });
          todoRows.push(todoProducts.get(product.handle));
        } else {
          todoProducts.get(product.handle).category = collection.title;
        }
      }
      await sleep(200);
    } catch (error) {
      console.error(`collection failed ${handle}: ${error.message}`);
    }
  }

  console.log("Fetching global products feed...");
  for (const product of await fetchAllProductsFeed()) {
    mergeProduct(productMap, product, "");
    if (!todoProducts.has(product.handle)) {
      const todo = {
        product_url: `${BASE}/products/${product.handle}`,
        category: "",
        status: "pending",
        error: "",
      };
      todoProducts.set(product.handle, todo);
      todoRows.push(todo);
    }
  }

  const rows = buildRows(productMap);
  const seen = new Set();
  const dedupedRows = rows.filter((row) => {
    const key = row.product_url;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  for (const todo of todoProducts.values()) {
    todo.status = seen.has(todo.product_url) || [...seen].some((url) => url.startsWith(`${todo.product_url}?`))
      ? "done"
      : "missing_or_filtered";
  }

  const todoPath = path.join(OUT_DIR, "todo_products.csv");
  const csvPath = path.join(OUT_DIR, "compumarts_products.csv");
  const jsonPath = path.join(OUT_DIR, "compumarts_products.json");
  const reportPath = path.join(OUT_DIR, "validation_report.json");

  writeCsv(todoPath, [...todoProducts.values()], ["product_url", "category", "status", "error"]);
  writeCsv(csvPath, dedupedRows, TARGET_COLUMNS);
  fs.writeFileSync(jsonPath, JSON.stringify(dedupedRows, null, 2), "utf8");

  const problems = validateRows(dedupedRows);
  const report = {
    site: BASE,
    scraped_at: nowCairo(),
    timezone: TZ,
    collections_discovered: todoCollections.size,
    unique_product_handles: productMap.size,
    exported_rows: dedupedRows.length,
    target_columns: TARGET_COLUMNS,
    validation_errors_sample: problems.slice(0, 50),
    validation_error_count: problems.length,
    note:
      dedupedRows.length < 100000
        ? "The public Shopify catalog exposed fewer than 100000 real product/variant rows. The scraper exported the maximum discovered without fabricating rows."
        : "",
  };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
  const zipPath = zipOutputs([todoPath, csvPath, jsonPath, reportPath]);

  console.log(JSON.stringify({ ...report, zip: zipPath }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
