import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const BASE_URL = "https://bashrety.tv";
const TZ = "Africa/Cairo";
const OUT_DIR = "output";
const TODO_FILE = path.join(OUT_DIR, "todo_products.csv");
const CLEAN_CSV = path.join(OUT_DIR, "bashrety_products_clean.csv");
const CLEAN_JSON = path.join(OUT_DIR, "bashrety_products_clean.json");
const ZIP_FILE = path.join(OUT_DIR, "bashrety_exports.zip");

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

const USER_AGENT =
  "Mozilla/5.0 (compatible; BashretyCatalogResearch/1.0; +https://bashrety.tv/)";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function ensureOutputDir() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

function cleanText(value) {
  if (value === undefined || value === null) return "";
  return String(value)
    .replace(/[®™©]/g, "")
    .replace(/[–—]/g, "-")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'")
    .replace(/[^\x20-\x7E]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function csvEscape(value) {
  const text = value === undefined || value === null ? "" : String(value);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function writeCsv(file, rows, columns) {
  const lines = [columns.join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => csvEscape(row[column] ?? "")).join(","));
  }
  fs.writeFileSync(file, `${lines.join("\n")}\n`, "utf8");
}

function parseCsv(file) {
  const text = fs.readFileSync(file, "utf8");
  const rows = [];
  let field = "";
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (inQuotes) {
      if (char === '"' && next === '"') {
        field += '"';
        i += 1;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }
  if (field.length || row.length) {
    row.push(field);
    rows.push(row);
  }
  const headers = rows.shift() ?? [];
  return rows
    .filter((items) => items.some((item) => item !== ""))
    .map((items) => Object.fromEntries(headers.map((header, i) => [header, items[i] ?? ""])));
}

async function fetchText(url, retries = 4) {
  let lastError;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {
        headers: { "user-agent": USER_AGENT, accept: "application/json,text/xml,text/html,*/*" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.text();
    } catch (error) {
      lastError = error;
      await sleep(500 * attempt);
    } finally {
      clearTimeout(timeout);
    }
  }
  throw lastError;
}

async function fetchJson(url) {
  return JSON.parse(await fetchText(url));
}

function extractLocs(xml) {
  return [...xml.matchAll(/<loc>\s*([^<]+?)\s*<\/loc>/gi)].map((match) =>
    match[1].replace(/&amp;/g, "&").trim(),
  );
}

function handleFromCollectionUrl(url) {
  const parsed = new URL(url);
  const parts = parsed.pathname.split("/").filter(Boolean);
  const idx = parts.indexOf("collections");
  if (idx === -1 || !parts[idx + 1]) return "";
  return parts[idx + 1];
}

function titleFromHandle(handle) {
  return handle
    .replace(/-/g, " ")
    .replace(/\band\b/g, "&")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .trim();
}

async function discoverCollections() {
  const sitemap = await fetchText(`${BASE_URL}/sitemap.xml`);
  const sitemapUrls = extractLocs(sitemap).filter((url) => /sitemap_collections/i.test(url));
  const collections = new Map();

  for (const sitemapUrl of sitemapUrls.filter((url) => !url.includes("/ar/"))) {
    const xml = await fetchText(sitemapUrl);
    for (const url of extractLocs(xml)) {
      if (url.includes("/ar/")) continue;
      const handle = handleFromCollectionUrl(url);
      if (handle && !collections.has(handle)) {
        collections.set(handle, {
          handle,
          url,
          subcategory: titleFromHandle(handle),
          category: standardCategory(titleFromHandle(handle), ""),
        });
      }
    }
  }

  collections.set("all", {
    handle: "all",
    url: `${BASE_URL}/collections/all`,
    subcategory: "All Products",
    category: "pharmacy > beauty and personal care",
  });

  return [...collections.values()].sort((a, b) => a.handle.localeCompare(b.handle));
}

async function discoverProducts() {
  ensureOutputDir();
  const collections = await discoverCollections();
  const byProductId = new Map();
  const errors = [];

  for (const collection of collections) {
    console.log(`collection ${collection.handle}`);
    let page = 1;
    while (true) {
      const url = `${BASE_URL}/collections/${encodeURIComponent(
        collection.handle,
      )}/products.json?limit=250&page=${page}`;
      try {
        const data = await fetchJson(url);
        const products = Array.isArray(data.products) ? data.products : [];
        if (!products.length) break;
        for (const product of products) {
          const key = String(product.id || product.handle || product.title);
          const productUrl = `${BASE_URL}/products/${product.handle}`;
          const current = byProductId.get(key);
          const categoryTrail = {
            product_category: collection.category,
            product_subcategory: collection.subcategory,
          };
          if (current) {
            current.categories.push(categoryTrail);
          } else {
            byProductId.set(key, {
              id: key,
              url: productUrl,
              handle: product.handle,
              title: cleanText(product.title),
              status: "pending",
              error: "",
              raw: product,
              categories: [categoryTrail],
            });
          }
        }
        console.log(
          `discovered ${products.length} products from ${collection.handle} page ${page}`,
        );
        page += 1;
        await sleep(150);
      } catch (error) {
        errors.push({ collection: collection.handle, page, error: error.message });
        break;
      }
    }
  }

  const rows = [...byProductId.values()].map((item) => {
    const primary = chooseCategory(item.categories, item.raw);
    return {
      url: item.url,
      category: primary.product_category,
      subcategory: primary.product_subcategory,
      status: item.status,
      error: item.error,
      product_id: item.id,
      handle: item.handle,
      title: item.title,
    };
  });

  writeCsv(TODO_FILE, rows, [
    "url",
    "category",
    "subcategory",
    "status",
    "error",
    "product_id",
    "handle",
    "title",
  ]);

  fs.writeFileSync(
    path.join(OUT_DIR, "discovery_errors.json"),
    JSON.stringify(errors, null, 2),
    "utf8",
  );
  fs.writeFileSync(
    path.join(OUT_DIR, "raw_products.json"),
    JSON.stringify([...byProductId.values()].map(({ raw, categories }) => ({ raw, categories })), null, 2),
    "utf8",
  );

  return { rows, errors };
}

function numberValue(value) {
  if (value === undefined || value === null || value === "") return "";
  const numeric = Number(String(value).replace(/[^0-9.]/g, ""));
  if (!Number.isFinite(numeric) || numeric <= 0) return "";
  return Number.isInteger(numeric) ? String(numeric) : String(numeric);
}

function discount(current, old) {
  const currentNumber = Number(current);
  const oldNumber = Number(old);
  if (!oldNumber || !currentNumber || oldNumber <= currentNumber) return "";
  return (((oldNumber - currentNumber) / oldNumber) * 100).toFixed(3);
}

function standardCategory(subcategory, tagsText) {
  const text = `${subcategory} ${tagsText}`.toLowerCase();
  if (/baby|diaper|kids/.test(text)) return "baby products";
  if (/hair|shampoo|dandruff|conditioner|lashes|nail/.test(text)) return "pharmacy > hair care";
  if (/sun|spf/.test(text)) return "pharmacy > sun care";
  if (/body|deodorant|hand|stretch|hygiene/.test(text)) return "pharmacy > body care";
  if (/acne|eczema|skin|face|cleanser|moistur|aging|pigmentation|eye|lip|mask|toner|serum|red face/.test(text)) {
    return "pharmacy > skin care";
  }
  if (/brand|all products/.test(text)) return "pharmacy > beauty and personal care";
  return "pharmacy > beauty and personal care";
}

function isUsefulSubcategory(value) {
  const text = cleanText(value).toLowerCase();
  if (!text) return false;
  if (
    /offer|sale|pick|best seller|campaign|campign|magazine|new arrival|bundle|summer|autumn|winter|spring|eid|ramadan|mother|valentine|test|brand|all products|all the family|\b20\d{2}\b/i.test(
      text,
    )
  ) {
    return false;
  }
  if (
    /^(acm|bionnex|dermactive|avene|eau thermale avene|eucerin|nuxe|mustela|ducray|uriage|isispharma|ecrinal|svr|matriskin|foltene pharma|organica|preventiva|rensaderm|perfederm|lca|bio oil)$/i.test(
      text,
    )
  ) {
    return false;
  }
  if (/acm bionnex|dermactive bionnex|dermactive dermactive baby|bionnex sun|uriage bionnex|avene bionnex|uriage mustela/i.test(text)) {
    return false;
  }
  return /acne|aging|hair|skin|sun|body|baby|clean|moistur|spot|pigment|eye|lip|mask|scrub|dandruff|deodorant|nail|lash|eczema|dry|oily|sensitive|red face|whiten|hydration|shampoo|conditioner|hygiene|diaper|stretch/i.test(
    text,
  );
}

function normalizeSubcategory(value) {
  return cleanText(value)
    .replace(/\s*-\s*/g, " ")
    .replace(/\s*&\s*/g, " & ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .trim();
}

function inferSubcategoryFromText(value) {
  const text = cleanText(value).toLowerCase();
  if (/sunscreen|sun screen|spf|sunblock|sun block|solaire/.test(text)) return "Sun Care";
  if (/anti[- ]?hair loss|hair transplant|fortifying.*hair|hair lotion|hair serum/.test(text)) {
    return "Anti Hair Loss Treatment";
  }
  if (/shampoo/.test(text)) return "Shampoos";
  if (/conditioner|hair mask|detangling/.test(text)) return "Conditioners & Masks";
  if (/hair/.test(text)) return "Hair Care";
  if (/eye contour|eye care|eye cream|caffeine/.test(text)) return "Eye Care";
  if (/whiten|depigment|neotone|pigment|brown spot/.test(text)) return "Brown Spot And Hyperpigmentation";
  if (/retinol|hyaluronic|vitamin c|glycolic|salicylic|aha|bha|toner|exfoliant|serum/.test(text)) {
    return "Face Care";
  }
  if (/cica|repair|emollient|eczema|atopic|soothing cleansing/.test(text)) return "Dry Skin Eczema Care";
  if (/hand cream|cracked heel|body lotion|baby oil|body oil|stretch mark/.test(text)) {
    return "Body Care Moisturizers";
  }
  if (/lip balm/.test(text)) return "Lip Care";
  if (/capsule|supplement/.test(text)) return "Supplements";
  if (/nursing|maternity|mom/.test(text)) return "Mom Care";
  if (/baby|kids|diaper|newborn/.test(text)) return "Baby Care";
  if (/mask|scrub/.test(text)) return "Masks & Scrubs";
  if (/cleanser|cleansing|micellar|make.?up remover/.test(text)) return "Cleansers";
  if (/cream|lotion|moistur|water essence/.test(text)) return "Moisturizers";
  return "";
}

function chooseCategory(categories, product) {
  const tagList = Array.isArray(product.tags) ? product.tags : [];
  const tags = tagList.join(" ");
  const tagSubcategory = tagList.map(normalizeSubcategory).find(isUsefulSubcategory);
  const collectionSubcategory = categories
    .map((item) => normalizeSubcategory(item.product_subcategory))
    .find(isUsefulSubcategory);
  const inferredSubcategory = inferSubcategoryFromText(
    `${product.title || ""} ${tags} ${cleanText(product.body_html || "")}`,
  );
  const fallback = normalizeSubcategory(
    categories.find((item) => !/all products|all brands|test/i.test(item.product_subcategory))
      ?.product_subcategory ||
      categories[0]?.product_subcategory ||
      "",
  );
  const subcategory = tagSubcategory || collectionSubcategory || inferredSubcategory || fallback;
  return {
    product_category: standardCategory(subcategory, tags),
    product_subcategory: subcategory,
  };
}

function extractUnit(text) {
  const match = text.match(
    /\b(\d+(?:[.,]\d+)?)\s?(ml|m[lL]|l|liter|litre|g|gm|gram|kg|pcs|pieces|capsules?|tabs?|tablets?|sachets?|ampoules?|spf\s?\d+)\b/i,
  );
  return match ? match[0].replace(/\s+/g, " ").toUpperCase() : "";
}

function extractWeight(text) {
  const match = text.match(/\b(\d+(?:[.,]\d+)?)\s?(ml|m[lL]|l|liter|litre|g|gm|gram|kg)\b/i);
  return match ? match[0].replace(/\s+/g, " ").toUpperCase() : "";
}

function extractRam(text) {
  const match = text.match(/\b(\d+)\s?GB\s?(RAM)?\b/i);
  return match && /ram/i.test(match[0]) ? `${match[1]}GB` : "";
}

function extractStorage(text) {
  const match = text.match(/\b(\d+)\s?(GB|TB)\s?(SSD|HDD|storage)?\b/i);
  if (!match || /ram/i.test(match[0])) return "";
  return `${match[1]}${match[2].toUpperCase()}${match[3] ? ` ${match[3].toUpperCase()}` : ""}`;
}

function cleanName(title, variantTitle) {
  let name = title;
  if (variantTitle && variantTitle !== "Default Title") {
    name = name.replace(new RegExp(`\\b${escapeRegExp(variantTitle)}\\b`, "i"), " ");
  }
  name = name.replace(/\b\d+(?:[.,]\d+)?\s?(ml|m[lL]|l|g|gm|kg|pcs|capsules?|tabs?|tablets?)\b/gi, " ");
  name = name.replace(/\s+/g, " ").trim();
  return name || title;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function productRowsFromRaw(rawEntry, todoByHandle, scrapingTime) {
  const product = rawEntry.raw;
  const categories = rawEntry.categories || [];
  const chosen = chooseCategory(categories, product);
  const variants = product.variants?.length ? product.variants : [{}];
  const imageUrl = product.images?.[0]?.src || "";
  const tagsText = Array.isArray(product.tags) ? product.tags.join(" ") : "";
  const baseText = cleanText(`${product.title} ${tagsText} ${product.body_html || ""}`);
  const brand = cleanText(product.vendor) || brandFromText(product.title, tagsText);
  const todo = todoByHandle.get(product.handle) || {};

  return variants.map((variant) => {
    const title =
      variant.title && variant.title !== "Default Title"
        ? cleanText(`${product.title} ${variant.title}`)
        : cleanText(product.title);
    const current = numberValue(variant.price);
    const rawOldPrice = numberValue(variant.compare_at_price);
    const oldPrice = Number(rawOldPrice) > Number(current) ? rawOldPrice : "";
    const unitText = `${title} ${variant.option1 || ""} ${variant.option2 || ""} ${variant.option3 || ""}`;
    return {
      title,
      name: cleanName(cleanText(product.title), variant.title),
      product_current_price: current,
      product_old_price: oldPrice,
      product_discount: discount(current, oldPrice),
      product_url: encodeURI(todo.url || `${BASE_URL}/products/${product.handle}`),
      product_image_url: encodeURI(imageUrl),
      product_seller: "Bashrety",
      product_availability: variant.available === false ? "out_of_stock" : "in_stock",
      product_category: chosen.product_category,
      product_subcategory: chosen.product_subcategory,
      product_unit: extractUnit(unitText) || extractUnit(baseText),
      product_weight: extractWeight(unitText) || extractWeight(baseText),
      scraping_time: scrapingTime,
      timestamp_timezone: TZ,
      product_brand: brand,
      product_ram: extractRam(baseText),
      product_storage: extractStorage(baseText),
    };
  });
}

function brandFromText(title, tagsText) {
  const firstTag = tagsText.split(/\s*,\s*|\s{2,}/).find(Boolean);
  return cleanText(firstTag || title.split(/\s+/).slice(0, 2).join(" "));
}

function validRow(row) {
  return (
    row.title &&
    row.product_url.startsWith("https://") &&
    row.product_image_url.startsWith("https://") &&
    row.product_current_price !== "" &&
    !/\b(undefined|null|nan)\b/i.test(Object.values(row).join(" "))
  );
}

async function scrapeProducts() {
  ensureOutputDir();
  if (!fs.existsSync(TODO_FILE) || !fs.existsSync(path.join(OUT_DIR, "raw_products.json"))) {
    await discoverProducts();
  }

  const todoRows = parseCsv(TODO_FILE);
  const todoByHandle = new Map(todoRows.map((row) => [row.handle, row]));
  const rawProducts = JSON.parse(fs.readFileSync(path.join(OUT_DIR, "raw_products.json"), "utf8"));
  const scrapingTime = new Intl.DateTimeFormat("sv-SE", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .format(new Date())
    .replace(" ", "T");

  const rows = rawProducts.flatMap((entry) => productRowsFromRaw(entry, todoByHandle, scrapingTime)).filter(validRow);
  const seen = new Set();
  const deduped = rows.filter((row) => {
    const key = `${row.product_url}|${row.title}|${row.product_current_price}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  writeCsv(CLEAN_CSV, deduped, TARGET_COLUMNS);
  fs.writeFileSync(CLEAN_JSON, JSON.stringify(deduped, null, 2), "utf8");

  const categoryByHandle = new Map(
    rawProducts.map((entry) => {
      const chosen = chooseCategory(entry.categories || [], entry.raw);
      return [entry.raw.handle, chosen];
    }),
  );
  const updatedTodo = todoRows.map((row) => {
    const chosen = categoryByHandle.get(row.handle);
    return {
      ...row,
      category: chosen?.product_category || row.category,
      subcategory: chosen?.product_subcategory || row.subcategory,
      status: "done",
      error: "",
    };
  });
  writeCsv(TODO_FILE, updatedTodo, [
    "url",
    "category",
    "subcategory",
    "status",
    "error",
    "product_id",
    "handle",
    "title",
  ]);

  createZip();
  return deduped;
}

function crc32(buffer) {
  let table = crc32.table;
  if (!table) {
    table = Array.from({ length: 256 }, (_, n) => {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      return c >>> 0;
    });
    crc32.table = table;
  }
  let crc = -1;
  for (const byte of buffer) crc = (crc >>> 8) ^ table[(crc ^ byte) & 0xff];
  return (crc ^ -1) >>> 0;
}

function dosTime(date = new Date()) {
  const time =
    (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const day = date.getDate();
  const month = date.getMonth() + 1;
  const year = Math.max(date.getFullYear() - 1980, 0);
  return { time, date: (year << 9) | (month << 5) | day };
}

function createZip() {
  const files = [TODO_FILE, CLEAN_CSV, CLEAN_JSON].filter((file) => fs.existsSync(file));
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  const dt = dosTime();

  for (const file of files) {
    const name = path.basename(file);
    const data = fs.readFileSync(file);
    const compressed = zlib.deflateRawSync(data);
    const nameBuffer = Buffer.from(name);
    const crc = crc32(data);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(dt.time, 10);
    local.writeUInt16LE(dt.date, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBuffer.length, 26);
    local.writeUInt16LE(0, 28);
    localParts.push(local, nameBuffer, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(dt.time, 12);
    central.writeUInt16LE(dt.date, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuffer.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);
    centralParts.push(central, nameBuffer);

    offset += local.length + nameBuffer.length + compressed.length;
  }

  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);

  fs.writeFileSync(ZIP_FILE, Buffer.concat([...localParts, ...centralParts, end]));
}

function validateOutputs() {
  const rows = parseCsv(CLEAN_CSV);
  const headers = fs.readFileSync(CLEAN_CSV, "utf8").split(/\r?\n/, 1)[0].split(",");
  const problems = [];
  if (headers.length !== TARGET_COLUMNS.length) problems.push(`column count ${headers.length}`);
  if (headers.join("|") !== TARGET_COLUMNS.join("|")) problems.push("header mismatch");
  rows.forEach((row, index) => {
    const n = index + 2;
    if (!row.title) problems.push(`row ${n}: missing title`);
    if (row.product_current_price && !/^\d+(\.\d+)?$/.test(row.product_current_price)) {
      problems.push(`row ${n}: invalid current price`);
    }
    if (row.product_old_price && !/^\d+(\.\d+)?$/.test(row.product_old_price)) {
      problems.push(`row ${n}: invalid old price`);
    }
    if (row.product_discount && !/^\d+(\.\d+)?$/.test(row.product_discount)) {
      problems.push(`row ${n}: invalid discount`);
    }
    if (!/^https:\/\//.test(row.product_url)) problems.push(`row ${n}: invalid product URL`);
    if (!/^https:\/\//.test(row.product_image_url)) problems.push(`row ${n}: invalid image URL`);
  });

  const summary = {
    rows: rows.length,
    columns: headers.length,
    header_matches: headers.join("|") === TARGET_COLUMNS.join("|"),
    problems: problems.slice(0, 50),
    total_problems: problems.length,
  };
  fs.writeFileSync(path.join(OUT_DIR, "validation_summary.json"), JSON.stringify(summary, null, 2));
  return summary;
}

async function main() {
  const command = process.argv[2] || "all";
  ensureOutputDir();
  if (command === "discover") {
    const result = await discoverProducts();
    console.log(`todo rows: ${result.rows.length}`);
    console.log(`discovery errors: ${result.errors.length}`);
  } else if (command === "scrape") {
    const rows = await scrapeProducts();
    console.log(`clean rows: ${rows.length}`);
  } else if (command === "validate") {
    console.log(JSON.stringify(validateOutputs(), null, 2));
  } else if (command === "all") {
    const discovery = await discoverProducts();
    const rows = await scrapeProducts();
    const validation = validateOutputs();
    console.log(
      JSON.stringify(
        {
          todo_rows: discovery.rows.length,
          clean_rows: rows.length,
          discovery_errors: discovery.errors.length,
          validation,
          files: { todo: TODO_FILE, csv: CLEAN_CSV, json: CLEAN_JSON, zip: ZIP_FILE },
        },
        null,
        2,
      ),
    );
  } else {
    throw new Error(`Unknown command: ${command}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
