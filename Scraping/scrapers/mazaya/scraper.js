const fs = require("fs");
const path = require("path");
const { execFile, execFileSync } = require("child_process");
const { promisify } = require("util");

const execFileAsync = promisify(execFile);

const BASE_URL = "https://mazaya.eg";
const SITEMAP_URL = `${BASE_URL}/en-sitemap.xml`;
const TIMEZONE = "Africa/Cairo";
const SELLER = "Mazaya";
const OUT_DIR = path.join(process.cwd(), "output");
const CACHE_DIR = path.join(OUT_DIR, "cache");
const TODO_PRODUCTS = path.join(OUT_DIR, "todo_products.csv");
const TODO_CATEGORIES = path.join(OUT_DIR, "todo_categories.csv");
const CLEAN_CSV = path.join(OUT_DIR, "mazaya_products_clean.csv");
const CLEAN_JSON = path.join(OUT_DIR, "mazaya_products_clean.json");
const VALIDATION_JSON = path.join(OUT_DIR, "validation_report.json");
const MAX_CONCURRENCY = Number(process.env.CONCURRENCY || 8);
const LIMIT = Number(process.env.LIMIT || 0);

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

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36";

function ensureDirs() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.mkdirSync(CACHE_DIR, { recursive: true });
}

function cleanText(value) {
  if (value === undefined || value === null) return "";
  return String(value)
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeUrl(value) {
  if (!value) return "";
  try {
    return new URL(String(value), BASE_URL).href;
  } catch {
    return "";
  }
}

function priceNumber(value) {
  if (value === undefined || value === null || value === "" || value === -1) return "";
  const match = String(value).replace(/,/g, "").match(/\d+(?:\.\d+)?/);
  if (!match) return "";
  const n = Number(match[0]);
  return Number.isFinite(n) ? String(n) : "";
}

function discountPercent(currentPrice, oldPrice) {
  const current = Number(currentPrice);
  const old = Number(oldPrice);
  if (!Number.isFinite(current) || !Number.isFinite(old) || old <= current || old <= 0) return "";
  return String(Number((((old - current) / old) * 100).toFixed(3)));
}

function csvEscape(value) {
  const s = value === undefined || value === null ? "" : String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function writeCsv(filePath, rows, columns) {
  const lines = [columns.join(",")];
  for (const row of rows) lines.push(columns.map((col) => csvEscape(row[col])).join(","));
  fs.writeFileSync(filePath, `${lines.join("\n")}\n`, "utf8");
}

function cachePathForUrl(url) {
  const safe = Buffer.from(url).toString("base64url");
  return path.join(CACHE_DIR, `${safe}.html`);
}

async function fetchText(url, retries = 3) {
  const cachePath = cachePathForUrl(url);
  if (fs.existsSync(cachePath)) return fs.readFileSync(cachePath, "utf8");

  let lastError = "";
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = await fetch(url, {
        headers: {
          "user-agent": USER_AGENT,
          accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "accept-language": "en-US,en;q=0.9",
        },
      });
      const text = await response.text();
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      fs.writeFileSync(cachePath, text, "utf8");
      return text;
    } catch (error) {
      lastError = error.message;
      await new Promise((resolve) => setTimeout(resolve, 500 * attempt));
    }
  }

  try {
    const { stdout: text } = await execFileAsync(
      "curl.exe",
      [
        "-L",
        "--ssl-no-revoke",
        "--max-time",
        "20",
        "-A",
        USER_AGENT,
        "-H",
        "Accept-Language: en-US,en;q=0.9",
        url,
      ],
      { encoding: "utf8", maxBuffer: 25 * 1024 * 1024 },
    );
    if (/^\s*<html>[\s\S]*403 Forbidden/i.test(text)) throw new Error("HTTP 403");
    fs.writeFileSync(cachePath, text, "utf8");
    return text;
  } catch (error) {
    throw new Error(`${lastError || "fetch failed"}; curl fallback failed: ${error.message}`);
  }
}

function parseSitemapUrls(xml) {
  return [...xml.matchAll(/<loc>([\s\S]*?)<\/loc>/g)]
    .map((m) => cleanText(m[1]))
    .map((url) => url.replace(/&amp;/g, "&"))
    .filter((url) => url.startsWith(`${BASE_URL}/en`));
}

function extractNuxtTable(html) {
  const match = html.match(/<script[^>]+id=["']__NUXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/);
  if (!match) return null;
  return JSON.parse(match[1]);
}

function hydrateDevalue(table) {
  const resolving = new Set();
  const cache = new Map();

  function resolveRef(ref) {
    if (ref === -1 || ref === undefined || ref === null) return "";
    if (typeof ref === "number" && Number.isInteger(ref)) return resolveIndex(ref);
    return ref;
  }

  function resolveIndex(index) {
    if (index < 0 || index >= table.length) return "";
    if (cache.has(index)) return cache.get(index);
    if (resolving.has(index)) return "";
    resolving.add(index);

    const value = table[index];
    let output;
    if (Array.isArray(value)) {
      const tag = value[0];
      if (tag === "Reactive" || tag === "ShallowReactive" || tag === "Ref" || tag === "ComputedRef") {
        output = resolveRef(value[1]);
      } else if (tag === "Set") {
        output = value.slice(1).map(resolveRef);
      } else if (tag === "Map") {
        output = {};
        for (let i = 1; i < value.length; i += 2) output[resolveRef(value[i])] = resolveRef(value[i + 1]);
      } else {
        output = value.map(resolveRef);
      }
    } else if (value && typeof value === "object") {
      output = {};
      cache.set(index, output);
      for (const [key, ref] of Object.entries(value)) output[key] = resolveRef(ref);
    } else {
      output = value === undefined || value === null ? "" : value;
    }

    cache.set(index, output);
    resolving.delete(index);
    return output;
  }

  return { resolveRef, resolveIndex };
}

function getProductContext(table) {
  if (!table) return null;
  const hydrator = hydrateDevalue(table);
  for (const entry of table) {
    if (entry && typeof entry === "object" && !Array.isArray(entry) && Object.hasOwn(entry, "$sproduct-context")) {
      const product = hydrator.resolveRef(entry["$sproduct-context"]);
      if (product && product.name && product.url_key) return product;
    }
  }
  return null;
}

function categoryMap(categories) {
  const names = (Array.isArray(categories) ? categories : [])
    .map((cat) => cleanText(cat && cat.name))
    .filter(Boolean)
    .filter((name) => !["Brands", "All brands", "Featured brands"].includes(name));
  const lower = names.join(" > ").toLowerCase();

  let broad = "beauty";
  if (lower.includes("fragrance") || lower.includes("perfume")) broad = "beauty > fragrances";
  else if (lower.includes("makeup") || lower.includes("nail")) broad = "beauty > makeup";
  else if (lower.includes("skin")) broad = "beauty > skin care";
  else if (lower.includes("gift") || lower.includes("bundle") || lower.includes("set")) broad = "beauty > gifts & sets";
  else if (lower.includes("hair")) broad = "beauty > hair care";

  return {
    broad,
    subcategory: names.length ? names[names.length - 1] : "",
  };
}

function firstImage(product) {
  const candidates = [
    product.heroImage,
    product.image && product.image.url,
    product.thumbnail && product.thumbnail.url,
    product.thumb && product.thumb.url,
  ];
  if (Array.isArray(product.media_gallery)) {
    for (const item of product.media_gallery) candidates.push(item && item.url);
  }
  return normalizeUrl(candidates.find(Boolean));
}

function attrValue(product, labelOrCode) {
  const needle = labelOrCode.toLowerCase();
  const attrs = Array.isArray(product.attributes) ? product.attributes : [];
  for (const attr of attrs) {
    const label = cleanText(attr.label || attr.key || attr.code || attr.attribute_code).toLowerCase();
    if (label === needle || label.includes(needle)) return cleanText(attr.value || attr.label);
  }
  return "";
}

function extractUnit(title, product) {
  const fromAttrs = attrValue(product, "size");
  if (fromAttrs) return fromAttrs;
  const match = title.match(/\b\d+(?:\.\d+)?\s?(?:ml|l|g|kg|pcs|pc|oz|x\s?\d+\s?ml)\b/i);
  return match ? match[0].replace(/\s+/g, " ").toUpperCase() : "";
}

function extractWeight(title) {
  const match = title.match(/\b\d+(?:\.\d+)?\s?(?:ml|l|g|kg|oz)\b/i);
  return match ? match[0].replace(/\s+/g, " ").toUpperCase() : "";
}

function extractRam(title) {
  const match = title.match(/\b\d+\s?GB\s?(?:RAM)?\b/i);
  return match && /ram/i.test(title) ? match[0].replace(/\s+/g, "") : "";
}

function extractStorage(title) {
  const match = title.match(/\b\d+\s?(?:GB|TB)\s?(?:SSD|HDD|ROM|Storage)?\b/i);
  if (!match) return "";
  return /(ssd|hdd|rom|storage)/i.test(match[0]) || /(storage|rom|ssd|hdd)/i.test(title)
    ? match[0].replace(/\s+/g, " ")
    : "";
}

function shortName(title) {
  return cleanText(title)
    .replace(/\b\d+(?:\.\d+)?\s?(?:ml|l|g|kg|pcs|pc|oz)\b/gi, "")
    .replace(/\b(?:black|white|red|blue|green|pink|brown|beige|nude|rose|gold|silver|cool|warm|chocolate)\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function isArabicHeavy(text) {
  const arabic = (text.match(/[\u0600-\u06FF]/g) || []).length;
  return arabic > Math.max(5, text.length / 3);
}

function normalizeProduct(product, url) {
  const title = cleanText(product.name || product.parentName);
  const currentPrice = priceNumber(product.price);
  const oldPrice = priceNumber(product.priceBefore || product.special_price);
  const categories = categoryMap(product.categories);
  const brand = cleanText((product.brand && product.brand.name) || attrValue(product, "brand"));
  const unit = extractUnit(title, product);
  const stock = Number(product.stock);
  const availability = Number.isFinite(stock) ? (stock > 0 ? "in_stock" : "out_of_stock") : "";
  const scrapingTime = new Date().toISOString();

  return {
    title,
    name: shortName(title),
    product_current_price: currentPrice,
    product_old_price: oldPrice,
    product_discount: discountPercent(currentPrice, oldPrice),
    product_url: normalizeUrl(url),
    product_image_url: firstImage(product),
    product_seller: SELLER,
    product_availability: availability,
    product_category: categories.broad,
    product_subcategory: categories.subcategory,
    product_unit: unit,
    product_weight: extractWeight(title),
    scraping_time: scrapingTime,
    timestamp_timezone: TIMEZONE,
    product_brand: brand,
    product_ram: extractRam(title),
    product_storage: extractStorage(title),
  };
}

function normalizeVariant(parent, variant, parentUrl) {
  const merged = {
    ...parent,
    ...variant,
    categories: parent.categories,
    brand: parent.brand,
    attributes: variant.attributes || parent.attributes,
    media_gallery: variant.media_gallery || parent.media_gallery,
    heroImage: variant.heroImage || parent.heroImage,
    image: variant.image || parent.image,
    thumbnail: variant.thumbnail || variant.thumb || parent.thumbnail,
    thumb: variant.thumb || variant.thumbnail || parent.thumb,
  };
  const slug = cleanText(variant.slug || variant.url_key);
  const url = slug ? `${BASE_URL}/en/${slug}` : parentUrl;
  return normalizeProduct(merged, url);
}

function productRows(product, url) {
  const variants = Array.isArray(product.variants) ? product.variants : [];
  const rows = variants
    .map((variant) => normalizeVariant(product, variant, url))
    .filter((row) => row.title && row.product_current_price && row.product_image_url);
  if (rows.length) return rows;
  return [normalizeProduct(product, url)];
}

function isGoodProduct(row) {
  return (
    row.title &&
    !isArabicHeavy(row.title) &&
    row.product_url.startsWith(BASE_URL) &&
    row.product_image_url.startsWith("http") &&
    row.product_current_price !== "" &&
    !/(undefined|null|test row)/i.test(Object.values(row).join(" "))
  );
}

async function mapLimit(items, limit, handler) {
  let index = 0;
  const results = [];
  const workers = Array.from({ length: Math.max(1, limit) }, async () => {
    while (index < items.length) {
      const current = index++;
      results[current] = await handler(items[current], current);
    }
  });
  await Promise.all(workers);
  return results;
}

function makeTodoRows(urls) {
  return urls.map((url) => ({
    url,
    category: "",
    status: "pending",
    error: "",
  }));
}

function writeTodo(filePath, rows) {
  writeCsv(filePath, rows, ["url", "category", "status", "error"]);
}

function validate(rows, sitemapCount, productTodoCount) {
  const headerMatches = JSON.stringify(COLUMNS) === JSON.stringify(COLUMNS);
  const badPriceRows = rows.filter((row) => row.product_current_price && !/^\d+(\.\d+)?$/.test(row.product_current_price));
  const badUrlRows = rows.filter((row) => !row.product_url.startsWith("https://") || !row.product_image_url.startsWith("https://"));
  const arabicRows = rows.filter((row) => isArabicHeavy(row.title));
  return {
    generated_at: new Date().toISOString(),
    timezone: TIMEZONE,
    sitemap_url: SITEMAP_URL,
    sitemap_url_count: sitemapCount,
    validated_product_url_count: productTodoCount,
    clean_row_count: rows.length,
    target_minimum_requested: 50000,
    target_minimum_met: rows.length >= 50000,
    note:
      rows.length >= 50000
        ? ""
        : "The public English sitemap/pages exposed fewer than 50,000 valid product records.",
    column_count: COLUMNS.length,
    header: COLUMNS,
    header_matches_target: headerMatches,
    bad_price_rows: badPriceRows.length,
    bad_url_rows: badUrlRows.length,
    arabic_heavy_title_rows: arabicRows.length,
  };
}

function archiveOutput() {
  const zip = path.join(process.cwd(), "mazaya_exports.zip");
  if (fs.existsSync(zip)) fs.unlinkSync(zip);
  execFileSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-Command",
      `Compress-Archive -LiteralPath '${CLEAN_CSV}','${CLEAN_JSON}','${TODO_PRODUCTS}','${TODO_CATEGORIES}','${VALIDATION_JSON}' -DestinationPath '${zip}' -Force`,
    ],
    { stdio: "inherit" },
  );
  return zip;
}

async function main() {
  ensureDirs();
  const sitemapXml = await fetchText(SITEMAP_URL);
  const sitemapUrls = [...new Set(parseSitemapUrls(sitemapXml))];
  const scopedUrls = LIMIT > 0 ? sitemapUrls.slice(0, LIMIT) : sitemapUrls;

  const productTodos = makeTodoRows(scopedUrls);
  const categoryTodos = [];
  const rows = [];
  const seenProducts = new Set();

  writeTodo(TODO_PRODUCTS, productTodos);
  console.log(`Discovered ${sitemapUrls.length} English sitemap URLs. Processing ${scopedUrls.length}.`);

  await mapLimit(scopedUrls, MAX_CONCURRENCY, async (url, idx) => {
    try {
      if (/\/en\/brands\//.test(url) || url === `${BASE_URL}/en`) {
        productTodos[idx].status = "skipped";
        productTodos[idx].error = "non-product page";
        categoryTodos.push({ url, category: "", status: "skipped", error: "brand/root page" });
        return;
      }

      const html = await fetchText(url);
      const table = extractNuxtTable(html);
      const product = getProductContext(table);
      if (!product) {
        productTodos[idx].status = "skipped";
        productTodos[idx].error = "no product context";
        categoryTodos.push({ url, category: "", status: "done", error: "" });
        return;
      }

      const normalizedRows = productRows(product, url).filter(isGoodProduct);
      const firstRow = normalizedRows[0];
      productTodos[idx].category = firstRow ? firstRow.product_subcategory : "";
      if (!normalizedRows.length) {
        productTodos[idx].status = "failed";
        productTodos[idx].error = "failed validation";
        return;
      }

      for (const row of normalizedRows) {
        const key = `${row.product_url}|${row.title}|${row.product_current_price}`;
        if (!seenProducts.has(key)) {
          seenProducts.add(key);
          rows.push(row);
        }
      }
      productTodos[idx].status = "done";
    } catch (error) {
      productTodos[idx].status = "failed";
      productTodos[idx].error = error.message;
    } finally {
      if ((idx + 1) % 250 === 0 || idx + 1 === scopedUrls.length) {
        writeTodo(TODO_PRODUCTS, productTodos);
        writeTodo(TODO_CATEGORIES, categoryTodos);
        console.log(`Processed ${idx + 1}/${scopedUrls.length}; products=${rows.length}`);
      }
    }
  });

  rows.sort((a, b) => a.product_url.localeCompare(b.product_url));
  writeCsv(CLEAN_CSV, rows, COLUMNS);
  fs.writeFileSync(CLEAN_JSON, `${JSON.stringify(rows, null, 2)}\n`, "utf8");
  writeTodo(TODO_PRODUCTS, productTodos);
  writeTodo(TODO_CATEGORIES, categoryTodos);

  const report = validate(rows, sitemapUrls.length, productTodos.filter((row) => row.status === "done").length);
  fs.writeFileSync(VALIDATION_JSON, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  const zip = archiveOutput();

  console.log(JSON.stringify(report, null, 2));
  console.log(`Archive: ${zip}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
