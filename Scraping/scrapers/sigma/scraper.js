import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const BASE_URL = "https://sigma-computer.com";
const MAIN_SITEMAP = `${BASE_URL}/sitemap.xml`;
const SEED_SITEMAPS = [
  MAIN_SITEMAP,
  `${BASE_URL}/en/item/sitemap.xml`,
  `${BASE_URL}/ar/item/sitemap.xml`,
];
const OUT_DIR = "output";
const CAIRO_TZ = "Africa/Cairo";
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
  "timestamp",
  "specifications",
];
const CLEAN_COLUMNS = [
  "product_family_id",
  "brand",
  "name",
  "title",
  "current_price",
  "old_price",
  "discount",
  "current_price_egp",
  "old_price_egp",
  "discount_percent",
  "category",
  "category_standard",
  "ram_gb",
  "storage_gb",
  "storage_type",
  "color",
  "img_URL",
  "url",
  "timescrapped",
  "timestamp",
  "specifications",
];

const args = parseArgs(process.argv.slice(2));
const delayMs = Number(args.delay ?? 500);
const sampleLimit = args.sample ? Number(args.sample) : null;
const productLimit = args["limit-products"] ? Number(args["limit-products"]) : null;
const concurrency = Number(args.concurrency ?? 8);
const categoryPageLimit = args["category-page-limit"]
  ? Number(args["category-page-limit"])
  : sampleLimit
    ? 3
    : args["crawl-categories"]
      ? Number.POSITIVE_INFINITY
      : 0;

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  const runStartedAt = zonedTimestamp();
  console.log(`[start] Sigma scrape at ${runStartedAt}`);
  console.log("[discover] Reading public sitemaps, category pages, pagination, and embedded data");

  const discovery = await discoverPublicSources();
  const categories = discovery.categories;
  await writeCsv(
    path.join(OUT_DIR, "categories_todo.csv"),
    ["category_url", "status", "page_count", "product_count", "error"],
    categories.map((url) => ({
      category_url: url,
      status: "pending",
      page_count: "",
      product_count: "",
      error: "",
    })),
  );

  const sitemapProducts = discovery.products;
  const categoryResult = await discoverCategoryProducts(categories, categoryPageLimit);
  const products = dedupeProducts([...categoryResult.products, ...sitemapProducts]);
  const plannedProducts = productLimit ? products.slice(0, productLimit) : products;
  const scrapeProducts = sampleLimit ? plannedProducts.slice(0, sampleLimit) : plannedProducts;

  await writeCsv(
    path.join(OUT_DIR, "products_todo.csv"),
    ["product_url", "source", "category_hint", "status", "error"],
    plannedProducts.map((item) => ({
      product_url: item.url,
      source: item.source,
      category_hint: item.categoryHint || "unknown",
      status: "pending",
      error: "",
    })),
  );

  console.log(
    `[discover] sitemaps=${discovery.sitemaps.length}, categories=${categories.length}, category_products=${categoryResult.products.length}, sitemap_products=${sitemapProducts.length}, unique_products=${products.length}`,
  );

  const { rows, failed } = await scrapeProductsConcurrent(scrapeProducts, runStartedAt);
  const finalRows = dedupeRowsByUrlOrSku(rows);

  const outputPath = path.join(OUT_DIR, sampleLimit ? "sigma_products_sample.csv" : "sigma_products.csv");
  const cleanOutputPath = path.join(OUT_DIR, sampleLimit ? "sigma_products_sample_clean.csv" : "sigma_products_clean.csv");
  const cleanRows = cleanProductRows(finalRows);
  await writeCsv(outputPath, COLUMNS, finalRows);
  await writeCsv(cleanOutputPath, CLEAN_COLUMNS, cleanRows);
  await writeCsv(path.join(OUT_DIR, "failed_products.csv"), ["product_url", "error"], failed);
  await writeAudit({
    runStartedAt,
    sitemapFilesVisited: discovery.sitemaps.length,
    categoriesCount: categories.length,
    categoryPagesVisited: categoryResult.pagesVisited,
    categoryProductsFound: categoryResult.products.length,
    sitemapProductsFound: sitemapProducts.length,
    uniqueProductsFound: products.length,
    plannedProducts: plannedProducts.length,
    scrapedRows: finalRows.length,
    cleanRows: cleanRows.length,
    badRowsRemovedInCleanExport: finalRows.length - cleanRows.length,
    duplicateRowsRemovedAfterSkuCheck: rows.length - finalRows.length,
    failedRows: failed.length,
    targetRows: 50000,
    outputPath,
    cleanOutputPath,
    sampleLimit: sampleLimit || "",
  });

  console.log(`[done] rows=${finalRows.length}, clean_rows=${cleanRows.length}, failed=${failed.length}, file=${outputPath}`);
}

async function scrapeProductsConcurrent(products, runStartedAt) {
  const rows = [];
  const failed = [];
  let cursor = 0;
  let completed = 0;

  async function worker() {
    while (cursor < products.length) {
      const index = cursor;
      cursor += 1;
      const item = products[index];
      try {
        if (delayMs > 0) await sleep(delayMs);
        const html = await fetchText(item.url);
        const row = parseProductPage(html, item, runStartedAt);
        if (!row.title || row.title === "unknown" || !row.url || row.url === "unknown") {
          failed.push({ product_url: item.url, error: "missing required title/url" });
          completed += 1;
          console.log(`[skip] ${completed}/${products.length} missing required fields`);
          continue;
        }
        rows[index] = row;
        completed += 1;
        console.log(`[scraped] ${completed}/${products.length} ${row.name}`);
      } catch (error) {
        failed.push({ product_url: item.url, error: String(error.message || error) });
        completed += 1;
        console.log(`[failed] ${completed}/${products.length} ${error.message || error}`);
      }
    }
  }

  const workers = Array.from({ length: Math.max(1, concurrency) }, () => worker());
  await Promise.all(workers);
  return { rows: rows.filter(Boolean), failed };
}

async function discoverPublicSources() {
  const sitemapUrls = await discoverSitemapUrls(SEED_SITEMAPS);
  const products = [];
  const categories = new Set();

  for (const sitemapUrl of sitemapUrls) {
    try {
      const xml = await fetchText(sitemapUrl);
      for (const loc of extractLocs(xml)) {
        if (isCategoryUrl(loc)) categories.add(normalizeLanguageUrl(loc, "en"));
        if (isProductUrl(loc)) {
          products.push({
            url: normalizeLanguageUrl(loc, "en"),
            source: sitemapUrl.includes("/ar/") ? "ar_item_sitemap" : "sitemap",
            categoryHint: "",
          });
        }
      }
    } catch (error) {
      console.log(`[sitemap failed] ${sitemapUrl} ${error.message || error}`);
    }
  }

  return { sitemaps: sitemapUrls, categories: [...categories].sort(), products };
}

async function discoverSitemapUrls(seedUrls) {
  const queue = [...new Set(seedUrls)];
  const seen = new Set();
  const sitemaps = [];

  while (queue.length) {
    const sitemapUrl = queue.shift();
    if (seen.has(sitemapUrl)) continue;
    seen.add(sitemapUrl);

    try {
      const xml = await fetchText(sitemapUrl);
      sitemaps.push(sitemapUrl);
      const locs = extractLocs(xml);
      const nested = locs.filter((url) => /sitemap.*\.xml(?:$|\?)/i.test(url) || /\/sitemap\.xml(?:$|\?)/i.test(url));
      for (const nestedUrl of nested) {
        if (sameHost(nestedUrl) && !seen.has(nestedUrl) && !queue.includes(nestedUrl)) queue.push(nestedUrl);
      }
    } catch (error) {
      console.log(`[sitemap failed] ${sitemapUrl} ${error.message || error}`);
    }
  }

  return sitemaps;
}

async function discoverCategoryProducts(categories, maxPages) {
  const products = [];
  let pagesVisited = 0;
  if (maxPages <= 0) return { products, pagesVisited };

  for (const categoryUrl of categories) {
    if (pagesVisited >= maxPages) break;
    let nextPages = [categoryUrl];
    const visited = new Set();
    let categoryProducts = 0;

    while (nextPages.length) {
      if (pagesVisited >= maxPages) break;
      const pageUrl = nextPages.shift();
      if (visited.has(pageUrl)) continue;
      visited.add(pageUrl);
      await sleep(delayMs);

      try {
        const html = await fetchText(pageUrl);
        pagesVisited += 1;
        const categoryName = extractCategoryTitle(html);
        const links = extractProductLinks(html).map((url) => ({
          url,
          source: "category_page",
          categoryHint: categoryName,
        }));
        categoryProducts += links.length;
        products.push(...links);

        for (const paginationUrl of extractPaginationLinks(html, pageUrl)) {
          if (!visited.has(paginationUrl) && !nextPages.includes(paginationUrl)) {
            nextPages.push(paginationUrl);
          }
        }
      } catch (error) {
        console.log(`[category failed] ${pageUrl} ${error.message || error}`);
      }
    }

    console.log(`[category] pages=${visited.size}, products=${categoryProducts}, ${categoryUrl}`);
  }

  return { products, pagesVisited };
}

function parseProductPage(html, item, runStartedAt) {
  const h1Match = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
  const title = h1Match?.[1] || titleFromMeta(html);
  const cleanTitle = cleanText(title);
  const productStart = h1Match?.index ?? Math.max(0, html.indexOf("<body"));
  const productSegment = html.slice(productStart, productStart + 25000);
  const breadcrumbSegment = html.slice(Math.max(0, productStart - 18000), productStart);
  const prices = uniqueMatches(productSegment, /(\d[\d,]*)\s*(?:<!--\s*-->\s*)?(?:<!--\s*-->\s*)?EGP/gi).map(normalizeNumber);
  const breadcrumbs = extractBreadcrumbs(breadcrumbSegment);
  const specs = extractSpecs(productSegment);
  const sku = extractSku(productSegment);
  const color = validColor(specs.color) || inferColor(cleanTitle) || "unknown";
  const imgUrl = extractImageUrl(productSegment) || extractImageUrl(html) || "unknown";
  const currentPrice = prices[0] || "";
  const oldPrice = prices[1] && prices[1] !== currentPrice ? prices[1] : "";
  const discount = extractDiscount(productSegment);
  const category = breadcrumbs.length ? breadcrumbs[breadcrumbs.length - 1] : item.categoryHint || "unknown";

  return cleanRow({
    title: cleanTitle || "unknown",
    current_price: currentPrice,
    old_price: oldPrice,
    discount,
    url: item.url,
    category,
    name: shortProductName(cleanTitle),
    color,
    img_URL: imgUrl,
    timescrapped: "1",
    timestamp: runStartedAt,
    specifications: Object.entries(specs)
      .concat(sku ? [["sku", sku]] : [])
      .filter(([key]) => key !== "color")
      .map(([key, value]) => `${key}: ${value}`)
      .join(" | ") || "unknown",
  });
}

function extractLocs(xml) {
  return [...xml.matchAll(/<loc>([\s\S]*?)<\/loc>/gi)].map((m) => decodeHtml(m[1].trim()));
}

function extractProductLinks(html) {
  const links = [
    ...uniqueMatches(html, /href="((?:https?:\/\/(?:www\.)?sigma-computer\.com)?\/(?:en|ar)\/item\?id=[^"]+)"/gi),
    ...uniqueMatches(html, /"(https?:\/\/(?:www\.)?sigma-computer\.com\/(?:en|ar)\/item\?id=[^"]+)"/gi),
    ...uniqueMatches(html, /"(\/(?:en|ar)\/item\?id=[^"]+)"/gi),
  ];
  return [...new Set(links)]
    .map((href) => normalizeLanguageUrl(new URL(decodeHtml(href), BASE_URL).toString(), "en"))
    .filter(isProductUrl);
}

function extractPaginationLinks(html, currentUrl) {
  const urls = uniqueMatches(html, /href="([^"]*(?:page|p)=\d+[^"]*)"/gi)
    .filter((href) => href.includes("/en/") || href.startsWith("?") || href.startsWith("/"))
    .map((href) => new URL(decodeHtml(href), currentUrl).toString());
  const pageIndexes = uniqueMatches(html, /data-index="(\d+)"/gi).map((value) => Number(value));
  const maxPage = Math.max(0, ...pageIndexes.filter(Number.isFinite));
  if (maxPage > 1) {
    const parsed = new URL(currentUrl);
    for (let page = 2; page <= maxPage; page += 1) {
      parsed.searchParams.set("page", String(page));
      urls.push(parsed.toString());
    }
  }
  return [...new Set(urls)];
}

function extractCategoryTitle(html) {
  const h1 = cleanText(firstMatch(html, /<h1[^>]*>([\s\S]*?)<\/h1>/i));
  if (h1) return h1;
  const title = cleanText(firstMatch(html, /<title[^>]*>([\s\S]*?)<\/title>/i));
  return title.replace(/\s*\|\s*Sigma Computer.*$/i, "") || "unknown";
}

function extractBreadcrumbs(html) {
  const crumbs = [];
  const breadcrumbSegment = firstMatch(html, /<ol[^>]*>([\s\S]*?)<\/ol>/i) || html;
  for (const match of breadcrumbSegment.matchAll(/<a[^>]*href="[^"]*(?:category|search)[^"]*"[^>]*>([\s\S]*?)<\/a>/gi)) {
    const value = cleanText(match[1]);
    if (value && !["Home", "All", "Stores"].includes(value) && !crumbs.includes(value)) crumbs.push(value);
  }
  return crumbs;
}

function extractSpecs(html) {
  const specs = {};
  const text = cleanText(
    html
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " "),
  );
  const labels = [
    "Brand",
    "Model",
    "Processor",
    "Memory",
    "Storage",
    "Graphics Card",
    "Screen Size",
    "Resolution",
    "Operating System",
    "Color",
    "Colour",
    "Warranty",
    "Weight",
  ];
  for (const label of labels) {
    const nextLabels = labels.filter((other) => other !== label).map(escapeRegex).join("|");
    const pattern = new RegExp(`(?:^|\\s)${escapeRegex(label)}:\\s*([\\s\\S]{1,220}?)(?=\\s+(?:${nextLabels}):|\\s+Show More|\\s+Specifications|$)`, "i");
    const value = cleanText(firstMatch(text, pattern));
    if (value && !looksLikeCss(value)) {
      specs[label.toLowerCase().replace(/\s+/g, "_").replace("colour", "color")] = value;
    }
  }
  return specs;
}

function extractSku(html) {
  return cleanText(firstMatch(html, /SKU:\s*<\/?[^>]*>\s*([A-Za-z0-9._\-\/]+)/i) || firstMatch(cleanText(html), /SKU:\s*([A-Za-z0-9._\-\/]+)/i));
}

function extractImageUrl(html) {
  const imageCandidates = [
    ...html.matchAll(/<img[^>]+(?:alt="[^"]*(?:Main view|Product Image)[^"]*"[^>]+)?(?:srcSet|src)="([^"]+)"/gi),
  ].map((match) => match[1]);
  const nextImage = imageCandidates.find((value) => value.includes("_next/image?url="));
  const raw =
    firstMatch(nextImage || "", /url=([^"&\s]+)/i) ||
    firstMatch(html, /srcSet="[^"]*url=([^"&]+)[^"]*"/i) ||
    firstMatch(html, /src="\/_next\/image\?url=([^"&]+)[^"]*"/i);
  if (!raw) return "";
  try {
    const decoded = decodeURIComponent(raw);
    return /sigma-logo|footer|loading/i.test(decoded) ? "" : decoded;
  } catch {
    return /sigma-logo|footer|loading/i.test(raw) ? "" : raw;
  }
}

function extractDiscount(html) {
  const save = firstMatch(html, /Save\s+(\d+)%/i);
  if (save) return save;
  const badge = firstMatch(html, />\s*-(\d+)%\s*</i);
  return badge || "";
}

function inferColor(title) {
  const colors = [
    "black",
    "white",
    "silver",
    "grey",
    "gray",
    "blue",
    "red",
    "green",
    "gold",
    "pink",
    "purple",
  ];
  const lower = title.toLowerCase();
  return colors.find((color) => new RegExp(`\\b${color}\\b`, "i").test(lower)) || "";
}

function validColor(value) {
  const clean = cleanText(value);
  if (!clean || clean.length > 60 || looksLikeCss(clean)) return "";
  return clean;
}

function looksLikeCss(value) {
  return /var\(|--|{|}|rgb\(|font-|user-select|chakra-|webkit-|moz-|line-height|border-|padding-|margin-/i.test(
    String(value || ""),
  );
}

function shortProductName(title) {
  const cleaned = cleanText(title);
  if (!cleaned) return "unknown";
  const firstPart = cleaned.split(/\s+-\s+/)[0].trim();
  return firstPart || cleaned.slice(0, 90).trim() || "unknown";
}

function titleFromMeta(html) {
  return firstMatch(html, /<title[^>]*>([\s\S]*?)(?:\s+-\s+[^|]+)?\s*\|\s*Sigma Computer<\/title>/i);
}

function cleanRow(row) {
  const cleaned = {};
  for (const column of COLUMNS) {
    let value = row[column];
    if (value === null || value === undefined) value = "";
    value = String(value).replace(/\b(?:null|undefined|NaN)\b/gi, "").trim();
    if (!value && !["old_price", "discount"].includes(column)) value = "unknown";
    cleaned[column] = value;
  }
  return cleaned;
}

function dedupeProducts(items) {
  const seen = new Set();
  const out = [];
  for (const item of items) {
    const key = productKey(item.url);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function productKey(url) {
  try {
    const parsed = new URL(url);
    return parsed.searchParams.get("id") || parsed.toString();
  } catch {
    return url;
  }
}

function dedupeRowsByUrlOrSku(rows) {
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    const sku = extractSkuFromSpecifications(row.specifications);
    const key = sku ? `sku:${sku.toLowerCase()}` : `url:${productKey(row.url)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

function extractSkuFromSpecifications(specifications) {
  const value = firstMatch(String(specifications || ""), /(?:^|\|\s*)sku:\s*([^|]+)/i);
  return cleanText(value);
}

function cleanProductRows(rows) {
  const cleaned = [];
  const seen = new Set();

  for (const row of rows) {
    const normalized = normalizeProductRow(row);
    if (!isGoodCleanRow(normalized)) continue;

    const dedupeKey = extractSkuFromSpecifications(normalized.specifications)
      ? `sku:${extractSkuFromSpecifications(normalized.specifications).toLowerCase()}`
      : `url:${productKey(normalized.url)}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    cleaned.push(normalized);
  }

  return cleaned;
}

function normalizeProductRow(row) {
  const title = fixText(row.title);
  const originalName = fixText(row.name || title);
  const specifications = fixText(row.specifications);
  const category = fixText(row.category);
  const categoryStandard = standardizeCategory(category, title);
  const brand = extractBrand(title, specifications);
  const name = cleanProductName(originalName || title, brand);
  const currentPrice = normalizePrice(row.current_price);
  const oldPrice = normalizePrice(row.old_price);
  const discount = normalizeDiscount(row.discount, currentPrice, oldPrice);
  const memory = detectMemory(title);
  const storage = detectStorage(title);
  const color = normalizeColor(fixText(row.color), title);
  const imageUrl = normalizeImageUrl(row.img_URL);
  const url = normalizeProductUrl(row.url);
  const familyId = productFamilyId({ brand, name, categoryStandard, ramGb: memory.ramGb, storageGb: storage.storageGb });

  return {
    product_family_id: familyId,
    brand,
    name,
    title,
    current_price: currentPrice === "" ? "" : String(currentPrice),
    old_price: oldPrice === "" ? "" : String(oldPrice),
    discount: discount === "" ? "" : String(discount),
    current_price_egp: currentPrice === "" ? "" : String(currentPrice),
    old_price_egp: oldPrice === "" ? "" : String(oldPrice),
    discount_percent: discount === "" ? "" : String(discount),
    category,
    category_standard: categoryStandard,
    ram_gb: memory.ramGb === "" ? "" : String(memory.ramGb),
    storage_gb: storage.storageGb === "" ? "" : String(storage.storageGb),
    storage_type: storage.storageType,
    color,
    img_URL: imageUrl,
    url,
    timescrapped: normalizeInteger(row.timescrapped) || "1",
    timestamp: fixText(row.timestamp),
    specifications,
  };
}

function isGoodCleanRow(row) {
  if (!row.url || row.url === "unknown" || !isProductUrl(row.url)) return false;
  if (!row.title || row.title === "unknown" || row.title.length < 3) return false;
  if (!row.name || row.name === "unknown" || row.name.length < 2) return false;
  if (!row.category_standard || row.category_standard === "unknown") return false;
  if (/\b(test|dummy|lorem ipsum)\b/i.test(row.title)) return false;
  return true;
}

function normalizePrice(value) {
  const text = fixText(value);
  if (!text || /^(unknown|nan|null|undefined)$/i.test(text)) return "";
  const number = text.replace(/[^\d.]/g, "");
  if (!number) return "";
  const parsed = Number(number);
  return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : "";
}

function normalizeDiscount(value, currentPrice, oldPrice) {
  const text = fixText(value);
  const explicit = text.replace(/[^\d.]/g, "");
  if (explicit) {
    const parsed = Number(explicit);
    if (Number.isFinite(parsed) && parsed >= 0) return Math.round(parsed);
  }
  if (currentPrice !== "" && oldPrice !== "" && oldPrice > currentPrice) {
    return Math.round(((oldPrice - currentPrice) / oldPrice) * 100);
  }
  return "";
}

function extractBrand(title, specifications) {
  const specBrand = fixText(firstMatch(specifications, /(?:^|\|\s*)brand:\s*([^|]+)/i));
  if (specBrand && specBrand !== "unknown" && specBrand.length <= 40) return canonicalBrand(specBrand);

  const text = fixText(title);
  const brands = [
    "ASUS",
    "LENOVO",
    "HP",
    "DELL",
    "MSI",
    "GIGABYTE",
    "AORUS",
    "SAMSUNG",
    "VIEWSONIC",
    "AOC",
    "PNY",
    "XFX",
    "SAPPHIRE",
    "ZOTAC",
    "INNO3D",
    "DEEPCOOL",
    "COOLER MASTER",
    "CORSAIR",
    "LIAN LI",
    "ANTEC",
    "XIGMATEK",
    "LOGITECH",
    "RAZER",
    "REDRAGON",
    "HAVIT",
    "AULA",
    "MEETION",
    "COUGAR",
    "KINGSTON",
    "CRUCIAL",
    "LEXAR",
    "WESTERN DIGITAL",
    "WD",
    "INTEL",
    "AMD",
    "THERMALRIGHT",
    "THERMAL GRIZZLY",
    "FANTECH",
    "FRACTAL DESIGN",
    "ARCTIC",
    "JONSBO",
    "PATRIOT",
    "TEAMGROUP",
    "TEAM GROUP",
    "XPG",
    "HYPERX",
    "UGREEN",
    "PHILIPS",
    "ACER",
  ];
  const upper = text.toUpperCase();
  const found = brands.find((brand) => new RegExp(`(^|[^A-Z0-9])${escapeRegex(brand)}([^A-Z0-9]|$)`).test(upper));
  if (found) return canonicalBrand(found);
  const firstToken = text.split(/\s+/)[0] || "";
  return canonicalBrand(firstToken) || "unknown";
}

function canonicalBrand(value) {
  const cleaned = fixText(value).replace(/[^A-Za-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const upper = cleaned.toUpperCase();
  const aliases = {
    GIGABAYT: "Gigabyte",
    GIGABYTE: "Gigabyte",
    AORUS: "Gigabyte",
    LENOVO: "Lenovo",
    ASUS: "ASUS",
    MSI: "MSI",
    HP: "HP",
    DELL: "Dell",
    WD: "Western Digital",
    "TEAM GROUP": "TeamGroup",
    TEAMGROUP: "TeamGroup",
  };
  if (aliases[upper]) return aliases[upper];
  return cleaned
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\bAmd\b/g, "AMD")
    .replace(/\bIntel\b/g, "Intel")
    .replace(/\bPny\b/g, "PNY")
    .replace(/\bAoc\b/g, "AOC")
    .replace(/\bXfx\b/g, "XFX");
}

function cleanProductName(name, brand) {
  let text = fixText(name)
    .replace(/\s*\|\s*Sigma Computer\s*$/i, "")
    .replace(/\s+-\s+(?:Main view|ASUS|MSI|Lenovo|HP|Dell)\s*$/i, "")
    .replace(/\b(?:features?|with|includes?)\b[\s\S]{80,}$/i, "")
    .replace(/\s+-\s*(?:Intel|AMD|NVIDIA|GeForce|Radeon|RTX|GTX|Core|Ryzen)\b[\s\S]*$/i, "")
    .replace(/,\s*(?:\d{3,5}\s*CUDA|PCIe|HDMI|DisplayPort|DP\s|FreeSync|G-Sync|HDR|built-in|VESA|Flicker|Eye Saver|brightness|contrast|refresh|response)[\s\S]*$/i, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  const commaParts = text.split(",");
  if (commaParts.length > 1 && commaParts[0].length >= 12) {
    text = commaParts[0].trim();
  }

  if (brand && brand !== "unknown") {
    const pattern = new RegExp(`^${escapeRegex(brand)}\\s+${escapeRegex(brand)}\\s+`, "i");
    text = text.replace(pattern, `${brand} `);
  }

  if (text.length > 120) {
    text = text.slice(0, 120).replace(/\s+\S*$/, "").trim();
  }

  return text || "unknown";
}

function detectMemory(title) {
  const text = fixText(title);
  const matches = [...text.matchAll(/(?:(\d+)\s*[xX]\s*)?(\d{1,3})\s*GB\s*(?:DDR\d|LPDDR\d|RAM|Memory|SO-?DIMM|SODIMM)?/gi)];
  const candidates = [];
  for (const match of matches) {
    const before = text.slice(Math.max(0, match.index - 20), match.index).toLowerCase();
    const after = text.slice(match.index, match.index + 45).toLowerCase();
    const memoryContext = /ddr\d|lpddr\d|ram|memory|so-?dimm|sodimm/i.test(match[0] + " " + after);
    if (!memoryContext && /(rtx|gtx|radeon|geforce|graphics|gddr|vram)/i.test(before + " " + after)) continue;
    const multiplier = match[1] ? Number(match[1]) : 1;
    const size = Number(match[2]);
    if (Number.isFinite(size) && size >= 2 && size <= 256) candidates.push(multiplier * size);
  }
  return { ramGb: candidates.length ? Math.max(...candidates) : "" };
}

function detectStorage(title) {
  const text = fixText(title);
  const patterns = [
    /(\d+(?:\.\d+)?)\s*TB\s*(?:SSD|NVME|M\.?2|HDD|SATA|PCIe|Storage)?/gi,
    /(\d{2,5})\s*GB\s*(?:SSD|NVME|M\.?2|HDD|SATA|PCIe|Storage)/gi,
  ];
  let bestGb = "";
  let type = "unknown";

  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      const raw = Number(match[1]);
      if (!Number.isFinite(raw)) continue;
      const gb = /TB/i.test(match[0]) ? raw * 1024 : raw;
      if (gb < 32 || gb > 65536) continue;
      if (bestGb === "" || gb > bestGb) {
        bestGb = Math.round(gb);
        type = detectStorageType(match[0]);
      }
    }
  }

  return { storageGb: bestGb, storageType: type };
}

function detectStorageType(value) {
  const text = value.toLowerCase();
  if (/nvme|m\.?2|pcie/.test(text)) return "NVMe SSD";
  if (/ssd|solid/.test(text)) return "SSD";
  if (/hdd|hard/.test(text)) return "HDD";
  return "unknown";
}

function standardizeCategory(category, title) {
  const text = `${fixText(category)} ${fixText(title)}`.toLowerCase();
  const rules = [
    ["laptop", /laptop|notebook|vivobook|zenbook|ideapad|thinkpad|legion|loq|victus|probook|predator|nitro lite/],
    ["monitor", /monitor|odyssey|viewsonic|evnia|\bfhd\b|\bqhd\b|ips|curved/],
    ["graphics_card", /graphics card|geforce|radeon|\brtx\b|\bgtx\b|\brx\s?\d/],
    ["processor", /processor|\bcpu\b|core i[3579]|ryzen/],
    ["motherboard", /motherboard|\bb\d{3}\b|\bz\d{3}\b|\ba\d{3}\b|\bh\d{3}\b|socket|am5|am4|lga/],
    ["memory", /\bram\b|ddr[45]|memory|sodimm|so-dimm/],
    ["storage", /\bssd\b|nvme|m\.2|hard drive|hdd|portable ssd|flash drive|jumpdrive/],
    ["case", /\bcase\b|tower|chassis/],
    ["power_supply", /power supply|\bpsu\b|\b\d{3,4}w\b|80\+|modular/],
    ["cooling", /cooler|cooling|fan|aio|liquid|thermal pad|thermal paste/],
    ["keyboard", /keyboard|keycaps|switches/],
    ["mouse", /\bmouse\b|dpi/],
    ["headset_audio", /headset|headphone|speaker|microphone|mic\b/],
    ["accessory", /bag|backpack|controller|gamepad|webcam|mouse pad|deskmat|stand|bracket|hub|adapter|battery/],
    ["desktop_bundle", /bundle|build|powered by/],
  ];
  const found = rules.find(([, regex]) => regex.test(text));
  return found ? found[0] : normalizeSlug(category || "unknown");
}

function normalizeColor(color, title) {
  const clean = fixText(color).toLowerCase();
  const simpleColors = ["black", "white", "silver", "grey", "gray", "blue", "red", "green", "gold", "pink", "purple"];
  if (clean && clean !== "unknown" && clean.length <= 40) {
    if (!simpleColors.includes(clean) || new RegExp(`\\b${escapeRegex(clean)}\\b`, "i").test(title)) return clean;
  }
  return inferColor(title) || "unknown";
}

function normalizeImageUrl(value) {
  const clean = fixText(value);
  if (!clean || clean === "unknown" || /sigma-logo|footer|loading/i.test(clean)) return "unknown";
  return clean;
}

function normalizeProductUrl(value) {
  try {
    return normalizeLanguageUrl(fixText(value), "en");
  } catch {
    return "";
  }
}

function normalizeInteger(value) {
  const number = String(value || "").replace(/[^\d]/g, "");
  return number || "";
}

function productFamilyId({ brand, name, categoryStandard, ramGb, storageGb }) {
  const base = normalizeSlug(
    [
      brand,
      categoryStandard,
      name
        .replace(/\b\d+\s*(?:gb|tb)\b/gi, " ")
        .replace(/\b(?:ddr\d|lpddr\d|rtx|gtx|radeon|geforce|intel|amd|core|ryzen)\b/gi, " ")
        .replace(/\s+/g, " "),
      ramGb || "",
      storageGb || "",
    ].join(" "),
  );
  return crypto.createHash("sha1").update(base || "unknown").digest("hex").slice(0, 12);
}

function normalizeSlug(value) {
  return fixText(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_{2,}/g, "_") || "unknown";
}

function fixText(value) {
  return decodeHtml(String(value || ""))
    .replace(/â€“|â€”/g, "-")
    .replace(/â€˜|â€™/g, "'")
    .replace(/â€œ|â€�/g, '"')
    .replace(/Â²/g, "²")
    .replace(/Â/g, "")
    .replace(/\uFFFD/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

async function cleanExistingCsv() {
  const inputPath = path.join(OUT_DIR, "sigma_products.csv");
  const outputPath = path.join(OUT_DIR, "sigma_products_clean.csv");
  const rows = parseCsv(await fs.readFile(inputPath, "utf8"));
  const cleanRows = cleanProductRows(rows);
  await writeCsv(outputPath, CLEAN_COLUMNS, cleanRows);
  await mergeAudit({
    cleanOutputPath: outputPath,
    cleanRows: cleanRows.length,
    badRowsRemovedInCleanExport: rows.length - cleanRows.length,
  });
}

async function mergeAudit(update) {
  const auditPath = path.join(OUT_DIR, "scrape_audit.json");
  let audit = {};
  try {
    audit = JSON.parse(await fs.readFile(auditPath, "utf8"));
  } catch {
    audit = {};
  }
  await fs.writeFile(auditPath, `${JSON.stringify({ ...audit, ...update }, null, 2)}\n`, "utf8");
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (inQuotes && char === '"' && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }

  const [headers, ...records] = rows;
  return records.map((record) =>
    Object.fromEntries(headers.map((header, index) => [header, record[index] ?? ""])),
  );
}

function isProductUrl(url) {
  try {
    const parsed = new URL(url, BASE_URL);
    return parsed.hostname.replace(/^www\./, "") === "sigma-computer.com" && /^\/(?:en|ar)\/item$/i.test(parsed.pathname) && parsed.searchParams.has("id");
  } catch {
    return false;
  }
}

function isCategoryUrl(url) {
  try {
    const parsed = new URL(url, BASE_URL);
    return parsed.hostname.replace(/^www\./, "") === "sigma-computer.com" && /^\/(?:en|ar)\/category\//i.test(parsed.pathname);
  } catch {
    return false;
  }
}

function normalizeLanguageUrl(url, language) {
  const parsed = new URL(url, BASE_URL);
  parsed.hostname = "sigma-computer.com";
  parsed.protocol = "https:";
  parsed.pathname = parsed.pathname.replace(/^\/(?:en|ar)(?=\/)/i, `/${language}`);
  parsed.hash = "";
  return parsed.toString();
}

function sameHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "") === "sigma-computer.com";
  } catch {
    return false;
  }
}

async function fetchText(url, retries = 3) {
  let lastError;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          "user-agent": "Mozilla/5.0 (compatible; SigmaScraper/1.0; educational data collection)",
          accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.text();
    } catch (error) {
      lastError = error;
      await sleep(500 * attempt);
    }
  }
  throw lastError;
}

async function writeCsv(filePath, columns, rows) {
  const lines = [columns.join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => csvCell(row[column] ?? "")).join(","));
  }
  await fs.writeFile(filePath, `${lines.join("\n")}\n`, "utf8");
}

async function writeAudit(data) {
  const gap = Math.max(0, data.targetRows - data.uniqueProductsFound);
  const audit = {
    ...data,
    targetGap: gap,
    targetStatus:
      gap === 0
        ? "target_met"
        : "target_not_met_site_exposes_fewer_distinct_public_english_products",
  };
  await fs.writeFile(path.join(OUT_DIR, "scrape_audit.json"), `${JSON.stringify(audit, null, 2)}\n`, "utf8");
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function parseArgs(argv) {
  const out = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      out[key] = true;
    } else {
      out[key] = next;
      index += 1;
    }
  }
  return out;
}

function firstMatch(text, regex) {
  const match = text.match(regex);
  return match ? match[1] : "";
}

function uniqueMatches(text, regex) {
  return [...new Set([...text.matchAll(regex)].map((match) => match[1]))];
}

function segmentAfter(html, needle, length) {
  if (!needle) return "";
  const index = html.indexOf(needle);
  return index >= 0 ? html.slice(index, index + length) : "";
}

function cleanText(value) {
  return decodeHtml(String(value || ""))
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function decodeHtml(value) {
  return String(value || "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function normalizeNumber(value) {
  return String(value || "").replace(/,/g, "").trim();
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function zonedTimestamp() {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: CAIRO_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "shortOffset",
  });
  return formatter.format(new Date()).replace(", ", "T").replace(" GMT", " GMT");
}

const isDirectRun = fileURLToPath(import.meta.url) === process.argv[1];
if (isDirectRun) {
  if (args["clean-existing"]) {
    cleanExistingCsv()
      .then(() => console.log("[done] clean export complete"))
      .catch((error) => {
        console.error(error);
        process.exit(1);
      });
  } else {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
  }
}
