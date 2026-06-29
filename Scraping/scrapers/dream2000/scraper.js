import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const BASE_URL = "https://dream2000.com/";
const DEFAULT_HEADERS = {
  "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "accept-language": "en-US,en;q=0.9,ar;q=0.8",
  "cache-control": "no-cache",
  "pragma": "no-cache",
  "user-agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
};

const COLUMNS = [
  "title",
  "current_price",
  "old_price",
  "discount",
  "url",
  "category",
  "name",
  "color",
  "img_URL",
  "timescrapped",
  "Timestamp with timezone"
];

const PRODUCT_LINK_HINTS = [
  "product-item-link",
  "product photo product-item-photo",
  "product-item-details"
];

const SKIP_URL_PARTS = [
  "/customer/",
  "/checkout/",
  "/wishlist/",
  "/catalogsearch/",
  "/sales/",
  "/review/",
  "/privacy",
  "/terms",
  "/about",
  "/contact",
  "/blog",
  "javascript:",
  "#"
];

function parseArgs(argv) {
  const args = {
    out: "output/dream2000_products.csv",
    todoDir: "output",
    delayMs: 1000,
    maxCategories: Infinity,
    maxProducts: Infinity,
    targetRows: Infinity,
    maxPagesPerCategory: 80,
    concurrency: 1,
    includeEnglish: false,
    rowMode: "unique",
    progressEvery: 100,
    fromTodo: "",
    appendExisting: "",
    discoverOnly: false
  };

  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === "--out") args.out = next, i += 1;
    else if (arg === "--todo-dir") args.todoDir = next, i += 1;
    else if (arg === "--delay-ms") args.delayMs = Number(next), i += 1;
    else if (arg === "--max-categories") args.maxCategories = Number(next), i += 1;
    else if (arg === "--max-products") args.maxProducts = Number(next), i += 1;
    else if (arg === "--target-rows") args.targetRows = Number(next), i += 1;
    else if (arg === "--max-pages-per-category") args.maxPagesPerCategory = Number(next), i += 1;
    else if (arg === "--concurrency") args.concurrency = Math.max(1, Number(next)), i += 1;
    else if (arg === "--include-english") args.includeEnglish = true;
    else if (arg === "--row-mode") args.rowMode = next, i += 1;
    else if (arg === "--progress-every") args.progressEvery = Math.max(1, Number(next)), i += 1;
    else if (arg === "--from-todo") args.fromTodo = next, i += 1;
    else if (arg === "--append-existing") args.appendExisting = next, i += 1;
    else if (arg === "--discover-only") args.discoverOnly = true;
    else if (arg === "--help") {
      printHelp();
      process.exit(0);
    }
  }

  return args;
}

function printHelp() {
  console.log(`Dream2000 scraper

Usage:
  npm run scrape -- [options]

Options:
  --out FILE                    Product CSV path. Default: output/dream2000_products.csv
  --todo-dir DIR                Directory for todo_categories.csv and todo_products.csv. Default: output
  --delay-ms N                  Delay between requests. Default: 1000
  --max-categories N            Limit categories for testing.
  --max-products N              Limit products for testing.
  --target-rows N               Stop product list at this many rows when possible.
  --max-pages-per-category N    Pagination safety limit. Default: 80
  --concurrency N               Product scrape concurrency. Keep low. Default: 1
  --row-mode unique|category    unique = one row per product URL, category = one row per product/category appearance.
  --progress-every N            Rewrite product todo after every N products. Default: 100
  --from-todo FILE              Skip discovery and scrape rows from an existing todo_products.csv.
  --append-existing FILE        Keep existing product CSV rows and scrape only new url/category keys.
  --discover-only               Build todo files, then stop before product page scraping.
  --include-english             Include English sitemaps as well as Arabic.
`);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function nowWithTimezone() {
  const d = new Date();
  const pad = (n, size = 2) => String(Math.trunc(Math.abs(n))).padStart(size, "0");
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const hours = pad(offset / 60);
  const minutes = pad(offset % 60);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${hours}:${minutes}`;
}

async function fetchText(url, { retries = 3, delayMs = 1000 } = {}) {
  let lastError;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, { headers: DEFAULT_HEADERS, redirect: "follow" });
      const text = await response.text();
      if (response.ok) return text;
      lastError = new Error(`HTTP ${response.status} for ${url}: ${text.slice(0, 120)}`);
    } catch (error) {
      lastError = error;
    }
    await sleep(delayMs * attempt);
  }
  throw lastError;
}

function normalizeUrl(rawUrl, base = BASE_URL) {
  try {
    const url = new URL(htmlDecode(rawUrl), base);
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (/^(utm_|fbclid|gclid|___store|___from_store)/i.test(key)) {
        url.searchParams.delete(key);
      }
    }
    return url.toString();
  } catch {
    return "";
  }
}

function htmlDecode(value = "") {
  return String(value)
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, "\"")
    .replace(/&#039;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#x2F;/g, "/");
}

function stripTags(value = "") {
  return clean(value.replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " "));
}

function clean(value) {
  if (value === null || value === undefined) return "";
  return htmlDecode(String(value))
    .replace(/\s+/g, " ")
    .replace(/\u00a0/g, " ")
    .trim();
}

function csvEscape(value) {
  const text = clean(value);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, "\"\"")}"`;
  return text;
}

function rowsToCsv(rows) {
  return [COLUMNS.join(","), ...rows.map((row) => COLUMNS.map((col) => csvEscape(row[col])).join(","))].join("\n") + "\n";
}

function todoRowsToCsv(rows) {
  const columns = ["status", "url", "category", "product_count", "error"];
  return [columns.join(","), ...rows.map((row) => columns.map((col) => csvEscape(row[col])).join(","))].join("\n") + "\n";
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (inQuotes) {
      if (char === "\"" && next === "\"") {
        field += "\"";
        i += 1;
      } else if (char === "\"") {
        inQuotes = false;
      } else {
        field += char;
      }
    } else if (char === "\"") {
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
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }

  const [headers = [], ...data] = rows;
  return data
    .filter((values) => values.some((value) => clean(value)))
    .map((values) => Object.fromEntries(headers.map((header, index) => [header, clean(values[index] || "")])));
}

function extractLocs(xml) {
  return [...xml.matchAll(/<loc>\s*([^<]+?)\s*<\/loc>/gi)].map((match) => normalizeUrl(match[1])).filter(Boolean);
}

function extractSitemaps(robots) {
  return robots
    .split(/\r?\n/)
    .map((line) => line.match(/^sitemap:\s*(.+)$/i)?.[1])
    .filter(Boolean)
    .map((url) => normalizeUrl(url));
}

function isSameSite(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "") === "dream2000.com";
  } catch {
    return false;
  }
}

function isLikelyCategory(url) {
  if (!url || !isSameSite(url)) return false;
  const lower = url.toLowerCase();
  if (!lower.endsWith(".html")) return false;
  if (SKIP_URL_PARTS.some((part) => lower.includes(part))) return false;
  return true;
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function extractLinks(html, baseUrl) {
  return unique(
    [...html.matchAll(/href\s*=\s*["']([^"']+)["']/gi)]
      .map((match) => normalizeUrl(match[1], baseUrl))
      .filter((url) => url && isSameSite(url))
  );
}

function extractProductLinksFromCategory(html, categoryUrl) {
  const links = new Set();

  for (const hint of PRODUCT_LINK_HINTS) {
    const escapedHint = hint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`<a[^>]+class=["'][^"']*${escapedHint}[^"']*["'][^>]+href=["']([^"']+)["']`, "gi");
    for (const match of html.matchAll(regex)) {
      const url = normalizeUrl(match[1], categoryUrl);
      if (isLikelyCategory(url)) links.add(url);
    }
  }

  return [...links];
}

function extractCategoryLinksFromCategory(html, categoryUrl, productUrls) {
  const productSet = new Set(productUrls);
  return extractLinks(html, categoryUrl)
    .filter((url) => isLikelyCategory(url))
    .filter((url) => url !== categoryUrl)
    .filter((url) => !url.includes("?p="))
    .filter((url) => !productSet.has(url));
}

function addPageParam(categoryUrl, pageNumber) {
  const url = new URL(categoryUrl);
  if (pageNumber > 1) url.searchParams.set("p", String(pageNumber));
  return url.toString();
}

function extractTitle(html) {
  return firstMatch(html, [
    /<meta\s+property=["']og:title["']\s+content=["']([^"']+)["']/i,
    /<meta\s+name=["']title["']\s+content=["']([^"']+)["']/i,
    /<h1[^>]*class=["'][^"']*page-title[^"']*["'][^>]*>([\s\S]*?)<\/h1>/i,
    /<title[^>]*>([\s\S]*?)<\/title>/i
  ]);
}

function extractH1(html) {
  return firstMatch(html, [
    /<h1[^>]*class=["'][^"']*page-title[^"']*["'][^>]*>([\s\S]*?)<\/h1>/i,
    /<h1[^>]*>([\s\S]*?)<\/h1>/i
  ]);
}

function firstMatch(html, regexes) {
  for (const regex of regexes) {
    const value = html.match(regex)?.[1];
    if (value) return stripTags(value);
  }
  return "";
}

function extractMeta(html, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return firstMatch(html, [
    new RegExp(`<meta\\s+property=["']${escaped}["']\\s+content=["']([^"']+)["']`, "i"),
    new RegExp(`<meta\\s+name=["']${escaped}["']\\s+content=["']([^"']+)["']`, "i"),
    new RegExp(`<meta\\s+content=["']([^"']+)["']\\s+property=["']${escaped}["']`, "i"),
    new RegExp(`<meta\\s+content=["']([^"']+)["']\\s+name=["']${escaped}["']`, "i")
  ]);
}

function extractJsonLdProducts(html) {
  const products = [];
  for (const match of html.matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    const text = clean(match[1]);
    if (!text) continue;
    try {
      const parsed = JSON.parse(text);
      collectJsonLdProduct(parsed, products);
    } catch {
      const fixed = text.replace(/,\s*([}\]])/g, "$1");
      try {
        collectJsonLdProduct(JSON.parse(fixed), products);
      } catch {
        // Ignore invalid embedded JSON-LD.
      }
    }
  }
  return products;
}

function collectJsonLdProduct(node, products) {
  if (!node) return;
  if (Array.isArray(node)) {
    for (const item of node) collectJsonLdProduct(item, products);
    return;
  }
  if (typeof node !== "object") return;
  const type = Array.isArray(node["@type"]) ? node["@type"].join(" ") : node["@type"];
  if (String(type || "").toLowerCase().includes("product")) products.push(node);
  if (node["@graph"]) collectJsonLdProduct(node["@graph"], products);
}

function extractPriceText(value) {
  const text = clean(value).replace(/,/g, "");
  const match = text.match(/(\d+(?:\.\d+)?)/);
  return match ? match[1] : "";
}

function extractPrices(html, product = {}) {
  const offer = Array.isArray(product.offers) ? product.offers[0] : product.offers || {};
  const jsonPrice = extractPriceText(offer.price || offer.lowPrice || offer.highPrice || "");
  const metaPrice = extractPriceText(extractMeta(html, "product:price:amount"));
  const specialPrice = extractPriceText(firstMatch(html, [
    /<span[^>]+class=["'][^"']*special-price[^"']*["'][\s\S]*?<span[^>]+class=["'][^"']*price[^"']*["'][^>]*>([\s\S]*?)<\/span>/i,
    /data-price-type=["']finalPrice["'][^>]+data-price-amount=["']([^"']+)["']/i
  ]));
  const dataAmounts = [...html.matchAll(/data-price-amount=["']([^"']+)["']/gi)].map((m) => Number(extractPriceText(m[1]))).filter(Number.isFinite);
  const current = jsonPrice || metaPrice || specialPrice || (dataAmounts.length ? String(Math.min(...dataAmounts)) : "");

  let oldPrice = extractPriceText(firstMatch(html, [
    /<span[^>]+class=["'][^"']*old-price[^"']*["'][\s\S]*?<span[^>]+class=["'][^"']*price[^"']*["'][^>]*>([\s\S]*?)<\/span>/i,
    /data-price-type=["']oldPrice["'][^>]+data-price-amount=["']([^"']+)["']/i
  ]));

  if (!oldPrice) {
    const saved = extractPriceText(firstMatch(html, [
      /(?:وفر|save)\s*([\d,.]+)/i,
      /<[^>]+class=["'][^"']*(?:discount|sale|save)[^"']*["'][^>]*>[\s\S]*?([\d,.]+)[\s\S]*?<\/[^>]+>/i
    ]));
    const currentNumber = Number(current);
    const savedNumber = Number(saved);
    if (Number.isFinite(currentNumber) && Number.isFinite(savedNumber) && savedNumber > 0) {
      oldPrice = String(currentNumber + savedNumber);
    }
  }

  return { current, old: oldPrice };
}

function extractDiscount(html, current, old) {
  const explicit = firstMatch(html, [
    /<span[^>]+class=["'][^"']*(?:discount|sale|save)[^"']*["'][^>]*>([\s\S]*?)<\/span>/i,
    /<div[^>]+class=["'][^"']*(?:discount|sale|save)[^"']*["'][^>]*>([\s\S]*?)<\/div>/i
  ]);
  if (explicit) return explicit;
  const c = Number(current);
  const o = Number(old);
  if (Number.isFinite(c) && Number.isFinite(o) && o > c) {
    return `${Math.round(((o - c) / o) * 100)}%`;
  }
  return "0";
}

function extractImage(html, product = {}, productUrl = BASE_URL) {
  const image = Array.isArray(product.image) ? product.image[0] : product.image;
  return normalizeUrl(image || extractMeta(html, "og:image") || firstMatch(html, [
    /<img[^>]+class=["'][^"']*(?:gallery-placeholder__image|fotorama__img|product-image-photo)[^"']*["'][^>]+src=["']([^"']+)["']/i
  ]), productUrl);
}

function extractBreadcrumbCategory(html) {
  const crumbsBlock = html.match(/<ul[^>]+class=["'][^"']*items[^"']*["'][^>]*>([\s\S]*?)<\/ul>/i)?.[1] || "";
  const crumbs = [...crumbsBlock.matchAll(/<li[^>]+class=["'][^"']*item[^"']*["'][^>]*>([\s\S]*?)<\/li>/gi)]
    .map((m) => stripTags(m[1]))
    .filter(Boolean)
    .filter((text) => !/^home$/i.test(text));
  if (crumbs.length > 1) crumbs.pop();
  return crumbs.length ? crumbs.join(" > ") : "";
}

function nameFromUrl(url) {
  try {
    const pathname = new URL(url).pathname;
    const slug = pathname.split("/").filter(Boolean).at(-1)?.replace(/\.html$/i, "") || "";
    return clean(slug.replace(/[-_]+/g, " "));
  } catch {
    return "";
  }
}

function extractColor(title, html) {
  const explicit = firstMatch(html, [
    /<span[^>]+class=["'][^"']*color[^"']*["'][^>]*>([\s\S]*?)<\/span>/i,
    /data-option-label=["']([^"']*(?:Black|White|Blue|Green|Red|Gold|Silver|Gray|Grey|Purple|Pink|Yellow|Orange|Brown|Beige)[^"']*)["']/i
  ]);
  if (explicit && explicit.length <= 80) return explicit;
  const colorPairs = [
    ["Black", "black|phantom black|أسود|اسود"],
    ["White", "white|أبيض|ابيض"],
    ["Blue", "blue|navy|twilight blue|أزرق|ازرق"],
    ["Green", "green|jade green|dark green|meadow green|أخضر|اخضر"],
    ["Red", "red|coral red|أحمر|احمر"],
    ["Gold", "gold|ذهبي"],
    ["Silver", "silver|فضي"],
    ["Gray", "gray|grey|رمادي"],
    ["Purple", "purple|violet|lavender|بنفسجي"],
    ["Pink", "pink|وردي"],
    ["Yellow", "yellow|أصفر|اصفر"],
    ["Orange", "orange|برتقالي"],
    ["Brown", "brown|بني"],
    ["Beige", "beige|بيج"],
    ["Midnight", "midnight"],
    ["Starlight", "starlight"],
    ["Titanium", "titanium"],
    ["Natural", "natural"],
    ["Graphite", "graphite"],
    ["Cream", "cream|كريمي"]
  ];
  const match = colorPairs.find(([, pattern]) => new RegExp(pattern, "i").test(title));
  if (match) return match[0];
  const fallbackPairs = [
    ["Black", "black|phantom black|\\u0623\\u0633\\u0648\\u062f|\\u0627\\u0633\\u0648\\u062f|\\u0628\\u0644\\u0627\\u0643"],
    ["White", "white|\\u0623\\u0628\\u064a\\u0636|\\u0627\\u0628\\u064a\\u0636"],
    ["Blue", "blue|navy|twilight blue|\\u0623\\u0632\\u0631\\u0642|\\u0627\\u0632\\u0631\\u0642|\\u0628\\u0644\\u0648"],
    ["Green", "green|jade green|dark green|meadow green|mint green|\\u0623\\u062e\\u0636\\u0631|\\u0627\\u062e\\u0636\\u0631|\\u062c\\u0631\\u064a\\u0646|\\u0645\\u064a\\u0646\\u062a"],
    ["Red", "red|coral red|\\u0623\\u062d\\u0645\\u0631|\\u0627\\u062d\\u0645\\u0631"],
    ["Gold", "gold|\\u0630\\u0647\\u0628\\u064a"],
    ["Silver", "silver|\\u0641\\u0636\\u064a"],
    ["Gray", "gray|grey|\\u0631\\u0645\\u0627\\u062f\\u064a|\\u062c\\u0631\\u0627\\u064a"],
    ["Purple", "purple|violet|lavender|\\u0628\\u0646\\u0641\\u0633\\u062c\\u064a"],
    ["Pink", "pink|\\u0648\\u0631\\u062f\\u064a"],
    ["Yellow", "yellow|\\u0623\\u0635\\u0641\\u0631|\\u0627\\u0635\\u0641\\u0631"],
    ["Orange", "orange|\\u0628\\u0631\\u062a\\u0642\\u0627\\u0644\\u064a|\\u0627\\u0648\\u0631\\u0646\\u062c|\\u0623\\u0648\\u0631\\u0646\\u062c"],
    ["Brown", "brown|\\u0628\\u0646\\u064a"],
    ["Beige", "beige|\\u0628\\u064a\\u062c"],
    ["Cream", "cream|\\u0643\\u0631\\u064a\\u0645\\u064a"]
  ];
  const fallback = fallbackPairs.find(([, pattern]) => new RegExp(pattern, "i").test(title));
  return fallback ? fallback[0] : "";
}

function parseProduct(html, url, fallbackCategory, timestamp, scrapeCount) {
  const product = extractJsonLdProducts(html)[0] || {};
  const title = clean(product.name || extractTitle(html) || nameFromUrl(url));
  const prices = extractPrices(html, product);
  const category = clean(fallbackCategory || extractBreadcrumbCategory(html));

  return {
    title,
    current_price: prices.current || "0",
    old_price: prices.old || "0",
    discount: extractDiscount(html, prices.current, prices.old),
    url,
    category,
    name: title || nameFromUrl(url),
    color: extractColor(title, html),
    img_URL: extractImage(html, product, url),
    timescrapped: String(scrapeCount),
    "Timestamp with timezone": timestamp
  };
}

async function discoverCategories(args) {
  const robots = await fetchText(new URL("/robots.txt", BASE_URL).toString(), { delayMs: args.delayMs });
  let sitemaps = extractSitemaps(robots);
  if (!args.includeEnglish) {
    sitemaps = sitemaps.filter((url) => !/sitemap_en_/i.test(url));
  }

  const categorySitemaps = sitemaps.filter((url) => /category/i.test(url));
  const categories = [];
  for (const sitemapUrl of categorySitemaps) {
    await sleep(args.delayMs);
    const xml = await fetchText(sitemapUrl, { delayMs: args.delayMs });
    categories.push(...extractLocs(xml).filter(isLikelyCategory));
  }

  return unique(categories).slice(0, args.maxCategories);
}

async function discoverProductsFromSitemap(args) {
  const robots = await fetchText(new URL("/robots.txt", BASE_URL).toString(), { delayMs: args.delayMs });
  let sitemaps = extractSitemaps(robots);
  if (!args.includeEnglish) {
    sitemaps = sitemaps.filter((url) => !/sitemap_en_/i.test(url));
  }

  const productSitemaps = sitemaps.filter((url) => /product/i.test(url));
  const products = [];
  for (const sitemapUrl of productSitemaps) {
    await sleep(args.delayMs);
    const xml = await fetchText(sitemapUrl, { delayMs: args.delayMs });
    products.push(...extractLocs(xml).filter(isLikelyCategory));
  }
  return unique(products);
}

async function crawlCategory(categoryUrl, args) {
  const found = new Set();
  const childCategories = new Set();
  let categoryName = nameFromUrl(categoryUrl);
  let stalePages = 0;

  for (let page = 1; page <= args.maxPagesPerCategory; page += 1) {
    const pageUrl = addPageParam(categoryUrl, page);
    const html = await fetchText(pageUrl, { delayMs: args.delayMs });
    if (page === 1) categoryName = extractH1(html) || categoryName;
    const before = found.size;
    const pageProductUrls = extractProductLinksFromCategory(html, pageUrl);
    for (const productUrl of pageProductUrls) {
      found.add(productUrl);
    }
    for (const childUrl of extractCategoryLinksFromCategory(html, pageUrl, pageProductUrls)) {
      childCategories.add(childUrl);
    }
    stalePages = found.size === before ? stalePages + 1 : 0;
    if (stalePages >= 2) break;
    if (!/[?&]p=\d+|toolbar-number|pages-item-next|class=["'][^"']*pages/i.test(html) && page > 1) break;
    await sleep(args.delayMs);
  }

  return { categoryName, productUrls: [...found], childCategories: [...childCategories] };
}

async function writeTodoFiles(todoDir, categoryTodos, productTodos) {
  await mkdir(todoDir, { recursive: true });
  await writeFile(path.join(todoDir, "todo_categories.csv"), todoRowsToCsv(categoryTodos), "utf8");
  await writeFile(path.join(todoDir, "todo_products.csv"), todoRowsToCsv(productTodos), "utf8");
}

async function loadProductTodos(filePath, maxRows) {
  const rows = parseCsv(await readFile(filePath, "utf8"))
    .filter((row) => row.url)
    .map((row) => ({
      status: "pending",
      url: normalizeUrl(row.url),
      category: row.category || "",
      product_count: row.product_count || "",
      error: ""
    }));
  return rows.slice(0, maxRows);
}

async function loadExistingProductRows(filePath) {
  try {
    return parseCsv(await readFile(filePath, "utf8"));
  } catch {
    return [];
  }
}

function productKey(row) {
  return `${row.url || ""}||${row.category || ""}`;
}

function cloneProductRow(baseRow, todo, index) {
  return {
    ...baseRow,
    category: clean(todo.category || baseRow.category),
    timescrapped: String(index + 1)
  };
}

async function scrapeProductTodos(productTodos, categoryTodos, args, timestamp) {
  const rows = new Array(productTodos.length);
  const todosByUrl = new Map();
  for (const todo of productTodos) {
    if (!todosByUrl.has(todo.url)) todosByUrl.set(todo.url, []);
    todosByUrl.get(todo.url).push(todo);
  }

  const uniqueUrls = [...todosByUrl.keys()];
  const parsedByUrl = new Map();
  console.log(`Scraping ${productTodos.length} rows from ${uniqueUrls.length} unique product URLs...`);

  await runLimited(uniqueUrls, args.concurrency, async (url, index) => {
    const relatedTodos = todosByUrl.get(url) || [];
    try {
      for (const todo of relatedTodos) todo.status = "running";
      if (index % args.progressEvery === 0) {
        await writeTodoFiles(args.todoDir, categoryTodos, productTodos);
      }

      const html = await fetchText(url, { delayMs: args.delayMs });
      parsedByUrl.set(url, parseProduct(html, url, "", timestamp, index + 1));
      for (const todo of relatedTodos) todo.status = "done";
    } catch (error) {
      for (const todo of relatedTodos) {
        todo.status = "error";
        todo.error = error.message;
      }
    }

    if ((index + 1) % args.progressEvery === 0 || index === uniqueUrls.length - 1) {
      let written = 0;
      for (let rowIndex = 0; rowIndex < productTodos.length; rowIndex += 1) {
        const todo = productTodos[rowIndex];
        const parsed = parsedByUrl.get(todo.url);
        if (parsed) {
          rows[rowIndex] = cloneProductRow(parsed, todo, rowIndex);
          written += 1;
        }
      }
      await writeFile(args.out, rowsToCsv([...(args.checkpointBaseRows || []), ...rows.filter(Boolean)]), "utf8");
      await writeTodoFiles(args.todoDir, categoryTodos, productTodos);
      console.log(`Progress: ${index + 1}/${uniqueUrls.length} unique URLs, ${written}/${productTodos.length} rows checkpointed`);
    }

    await sleep(args.delayMs);
  });

  return rows.filter(Boolean);
}

async function runLimited(items, concurrency, worker) {
  const results = [];
  let index = 0;
  async function next() {
    while (index < items.length) {
      const currentIndex = index;
      index += 1;
      results[currentIndex] = await worker(items[currentIndex], currentIndex);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, next));
  return results;
}

async function main() {
  const args = parseArgs(process.argv);
  if (!["unique", "category"].includes(args.rowMode)) {
    throw new Error("--row-mode must be either unique or category");
  }

  await mkdir(path.dirname(args.out), { recursive: true });
  await mkdir(args.todoDir, { recursive: true });

  const timestamp = nowWithTimezone();
  let categoryTodos = [];
  let productTodos = [];

  if (args.fromTodo) {
    const existingRows = args.appendExisting ? await loadExistingProductRows(args.appendExisting) : [];
    const existingKeys = new Set(existingRows.map(productKey));
    productTodos = await loadProductTodos(args.fromTodo, Infinity);
    if (existingKeys.size) {
      productTodos = productTodos.filter((row) => !existingKeys.has(productKey(row)));
    }
    const wantedRows = Number.isFinite(args.targetRows)
      ? Math.max(0, args.targetRows - existingRows.length)
      : args.maxProducts;
    productTodos = productTodos.slice(0, Math.min(args.maxProducts, wantedRows));
    args.checkpointBaseRows = existingRows;
    await writeTodoFiles(args.todoDir, categoryTodos, productTodos);
    const cleanRows = await scrapeProductTodos(productTodos, categoryTodos, args, timestamp);
    const finalRows = [...existingRows, ...cleanRows];
    await writeFile(args.out, rowsToCsv(finalRows), "utf8");
    const stats = [
      `timestamp,${csvEscape(timestamp)}`,
      `row_mode,${csvEscape(args.rowMode)}`,
      `source_todo,${csvEscape(args.fromTodo)}`,
      `append_existing,${csvEscape(args.appendExisting)}`,
      `target_rows,${Number.isFinite(args.targetRows) ? args.targetRows : ""}`,
      `existing_rows,${existingRows.length}`,
      `new_rows,${cleanRows.length}`,
      `written_rows,${finalRows.length}`,
      `unique_product_urls,${new Set(finalRows.map((row) => row.url)).size}`,
      `categories_seen,0`,
      `category_rows_done,0`,
      `product_errors,${productTodos.filter((row) => row.status === "error").length}`
    ].join("\n") + "\n";
    await writeFile(path.join(args.todoDir, "scrape_stats.csv"), stats, "utf8");
    console.log(`Done. Wrote ${finalRows.length} clean product rows to ${args.out}`);
    console.log(`Todo files: ${path.join(args.todoDir, "todo_categories.csv")} and ${path.join(args.todoDir, "todo_products.csv")}`);
    return;
  }

  console.log("Discovering categories from robots.txt sitemaps...");
  const categories = await discoverCategories(args);
  categoryTodos = categories.map((url) => ({ status: "pending", url, category: nameFromUrl(url), product_count: "0", error: "" }));
  const seenCategoryUrls = new Set(categoryTodos.map((row) => row.url));
  const productTodoByKey = new Map();
  const productCategoriesByUrl = new Map();

  await writeTodoFiles(args.todoDir, categoryTodos, []);
  console.log(`Found ${categories.length} categories.`);

  for (let i = 0; i < categoryTodos.length; i += 1) {
    const todo = categoryTodos[i];
    try {
      todo.status = "running";
      await writeTodoFiles(args.todoDir, categoryTodos, [...productTodoByKey.values()]);
      const { categoryName, productUrls, childCategories } = await crawlCategory(todo.url, args);
      todo.category = categoryName;
      todo.product_count = String(productUrls.length);
      todo.status = "done";
      for (const childUrl of childCategories) {
        if (!seenCategoryUrls.has(childUrl) && categoryTodos.length < args.maxCategories) {
          seenCategoryUrls.add(childUrl);
          categoryTodos.push({ status: "pending", url: childUrl, category: nameFromUrl(childUrl), product_count: "0", error: "" });
        }
      }
      for (const productUrl of productUrls) {
        if (!productCategoriesByUrl.has(productUrl)) productCategoriesByUrl.set(productUrl, new Set());
        productCategoriesByUrl.get(productUrl).add(categoryName);

        const key = args.rowMode === "category" ? `${productUrl}||${categoryName}` : productUrl;
        if (!productTodoByKey.has(key)) {
          productTodoByKey.set(key, { status: "pending", url: productUrl, category: categoryName, product_count: "", error: "" });
        }
      }
    } catch (error) {
      todo.status = "error";
      todo.error = error.message;
    }
    await writeTodoFiles(args.todoDir, categoryTodos, [...productTodoByKey.values()]);
    if (productTodoByKey.size >= args.targetRows) {
      console.log(`Target row list reached ${productTodoByKey.size}; stopping category discovery early.`);
      break;
    }
    await sleep(args.delayMs);
  }

  console.log("Adding product URLs from product sitemap for maximum coverage...");
  try {
    const sitemapProducts = await discoverProductsFromSitemap(args);
    for (const productUrl of sitemapProducts) {
      if (!productTodoByKey.has(productUrl) && args.rowMode === "unique") {
        productTodoByKey.set(productUrl, { status: "pending", url: productUrl, category: "", product_count: "", error: "" });
      } else if (args.rowMode === "category" && !productCategoriesByUrl.has(productUrl)) {
        const key = `${productUrl}||`;
        productTodoByKey.set(key, { status: "pending", url: productUrl, category: "", product_count: "", error: "" });
      }
    }
  } catch (error) {
    console.warn(`Could not read product sitemap: ${error.message}`);
  }

  productTodos = [...productTodoByKey.values()];
  const productLimit = Math.min(args.maxProducts, args.targetRows);
  productTodos = productTodos.slice(0, productLimit);
  await writeTodoFiles(args.todoDir, categoryTodos, productTodos);
  if (args.discoverOnly) {
    const stats = [
      `timestamp,${csvEscape(timestamp)}`,
      `row_mode,${csvEscape(args.rowMode)}`,
      `target_rows,${Number.isFinite(args.targetRows) ? args.targetRows : ""}`,
      `todo_rows,${productTodos.length}`,
      `unique_product_urls,${new Set(productTodos.map((row) => row.url)).size}`,
      `categories_seen,${categoryTodos.length}`,
      `category_rows_done,${categoryTodos.filter((row) => row.status === "done").length}`,
      `product_errors,0`
    ].join("\n") + "\n";
    await writeFile(path.join(args.todoDir, "scrape_stats.csv"), stats, "utf8");
    console.log(`Discovery complete. Wrote ${productTodos.length} product todo rows.`);
    return;
  }

  const cleanRows = await scrapeProductTodos(productTodos, categoryTodos, args, timestamp);
  await writeFile(args.out, rowsToCsv(cleanRows), "utf8");
  const stats = [
    `timestamp,${csvEscape(timestamp)}`,
    `row_mode,${csvEscape(args.rowMode)}`,
    `target_rows,${Number.isFinite(args.targetRows) ? args.targetRows : ""}`,
    `written_rows,${cleanRows.length}`,
    `unique_product_urls,${new Set(cleanRows.map((row) => row.url)).size}`,
    `categories_seen,${categoryTodos.length}`,
    `category_rows_done,${categoryTodos.filter((row) => row.status === "done").length}`,
    `product_errors,${productTodos.filter((row) => row.status === "error").length}`
  ].join("\n") + "\n";
  await writeFile(path.join(args.todoDir, "scrape_stats.csv"), stats, "utf8");
  console.log(`Done. Wrote ${cleanRows.length} clean product rows to ${args.out}`);
  console.log(`Todo files: ${path.join(args.todoDir, "todo_categories.csv")} and ${path.join(args.todoDir, "todo_products.csv")}`);
}

main().then(() => {
  process.exit(0);
}).catch((error) => {
  console.error(error);
  process.exit(1);
});
