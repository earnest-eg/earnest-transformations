#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const BASE = 'https://www.toptoyseg.com/';
const TZ = 'Africa/Cairo';
const OUT_DIR = path.join(process.cwd(), 'output');
const TODO_CSV = path.join(OUT_DIR, 'todo_products.csv');
const RAW_JSONL = path.join(OUT_DIR, 'products_raw.jsonl');
const CLEAN_CSV = path.join(OUT_DIR, 'toptoys_products_clean.csv');
const CLEAN_JSON = path.join(OUT_DIR, 'toptoys_products_clean.json');
const REPORT_JSON = path.join(OUT_DIR, 'scrape_report.json');
const ZIP_PATH = path.join(OUT_DIR, 'toptoys_exports.zip');

const COLUMNS = [
  'title',
  'name',
  'product_current_price',
  'product_old_price',
  'product_discount',
  'product_url',
  'product_image_url',
  'product_seller',
  'product_availability',
  'product_category',
  'product_subcategory',
  'product_unit',
  'product_weight',
  'scraping_time',
  'timestamp_timezone',
  'product_brand',
  'product_ram',
  'product_storage',
];

const args = parseArgs(process.argv.slice(2));
const mode = args.mode || 'all';
const concurrency = Number(args.concurrency || 8);
const limit = args.limit ? Number(args.limit) : 0;
const delayMs = Number(args.delay || 120);
const maxCategoryPages = Number(args.maxCategoryPages || 80);
const requestTimeoutMs = Number(args.timeout || 20000);
const crawlCategories = Boolean(args.categories);
const startPage = Number(args.startPage || 1);
const endPage = args.endPage ? Number(args.endPage) : 0;
const userAgent = args.userAgent || 'Mozilla/5.0 (compatible; TopToysDataCollector/1.0; +https://www.toptoyseg.com/)';

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});

async function main() {
  ensureDir(OUT_DIR);
  if (mode === 'discover' || mode === 'all') {
    const discovered = await discoverUrls();
    writeTodo(discovered);
    console.log(`discovered ${discovered.length} unique candidate product URLs`);
  }

  if (mode === 'listings' || mode === 'all') {
    await scrapeShopListings();
  }

  if (mode === 'scrape' || mode === 'all') {
    const todo = readTodo();
    const existing = readExistingRaw();
    const pending = todo
      .filter((row) => row.status !== 'done' && !existing.has(row.url))
      .slice(0, limit > 0 ? limit : undefined);
    console.log(`scraping ${pending.length} pending product URLs (${existing.size} already scraped)`);
    await scrapeProducts(pending);
  }

  if (mode === 'normalize' || mode === 'scrape' || mode === 'all') {
    const rows = normalizeRows(readRawRows());
    writeClean(rows);
    writeReport(rows);
    archiveExports();
    console.log(`exported ${rows.length} clean rows`);
  }
}

async function discoverUrls() {
  const sitemapUrls = await getSitemapChildren(`${BASE}sitemap.xml`);
  const productSitemaps = sitemapUrls.filter((url) => /product-sitemap\d+\.xml$/i.test(url));
  const categorySitemap = sitemapUrls.find((url) => /product_cat-sitemap\.xml$/i.test(url));

  const productMap = new Map();
  for (const sitemap of productSitemaps) {
    try {
      const urls = await getUrlset(sitemap);
      for (const url of urls) {
        if (/\/product\/[^/]+\/?$/i.test(url)) {
          addProduct(productMap, url, '', 'sitemap');
        }
      }
      console.log(`sitemap ${path.basename(sitemap)}: ${urls.length} URLs`);
    } catch (error) {
      console.warn(`sitemap failed ${sitemap}: ${error.message}`);
    }
  }

  if (categorySitemap && crawlCategories) {
    const categories = await getUrlset(categorySitemap);
    for (const categoryUrl of categories) {
      const categoryLabel = categoryFromUrl(categoryUrl);
      for (let page = 1; page <= maxCategoryPages; page += 1) {
        const url = page === 1 ? categoryUrl : joinUrl(categoryUrl, `page/${page}/`);
        let html = '';
        try {
          html = await fetchText(url);
        } catch (error) {
          if (page === 1) console.warn(`category failed ${categoryUrl}: ${error.message}`);
          break;
        }
        const links = extractProductLinks(html);
        if (links.length === 0) break;
        for (const link of links) addProduct(productMap, link, categoryLabel, 'category');
        const hasNext = /class=["'][^"']*(?:next|page-numbers)[^"']*["'][^>]*>/i.test(html) && html.includes(`/page/${page + 1}/`);
        if (!hasNext && page > 1) break;
        await sleep(delayMs);
      }
      console.log(`category ${categoryLabel || categoryUrl}: total candidates ${productMap.size}`);
    }
  } else if (categorySitemap) {
    console.log('category page walking skipped; pass --categories to enable it');
  }

  return [...productMap.values()].sort((a, b) => a.url.localeCompare(b.url));
}

async function scrapeProducts(todoRows) {
  let done = 0;
  let failed = 0;
  const allTodoRows = readTodo();
  const todoByUrl = new Map(allTodoRows.map((row) => [row.url, row]));
  await asyncPool(concurrency, todoRows, async (todoRow) => {
    await sleep(delayMs);
    try {
      const product = await scrapeOne(todoRow);
      appendJsonl(RAW_JSONL, product);
      updateTodoStatus(todoByUrl, todoRow.url, 'done', '');
      done += 1;
    } catch (error) {
      updateTodoStatus(todoByUrl, todoRow.url, 'error', error.message.slice(0, 300));
      failed += 1;
    }
    const total = done + failed;
    if (total % 100 === 0 || total === todoRows.length) {
      writeTodo(allTodoRows);
      console.log(`progress ${total}/${todoRows.length}, done=${done}, failed=${failed}`);
    }
  });
  writeTodo(allTodoRows);
}

async function scrapeShopListings() {
  const existing = readExistingRaw();
  const firstHtml = startPage <= 1 ? await fetchText(`${BASE}shop/`) : await fetchText(`${BASE}shop/page/${startPage}/`);
  const totalPages = extractMaxPage(firstHtml) || 1;
  const lastPage = endPage > 0 ? Math.min(endPage, totalPages) : totalPages;
  let added = scrapeListingHtml(firstHtml, startPage <= 1 ? `${BASE}shop/` : `${BASE}shop/page/${startPage}/`, existing);
  console.log(`shop page ${startPage}/${lastPage}: added ${added}`);
  for (let page = startPage + 1; page <= lastPage; page += 1) {
    await sleep(delayMs);
    try {
      const html = await fetchText(`${BASE}shop/page/${page}/`);
      added += scrapeListingHtml(html, `${BASE}shop/page/${page}/`, existing);
    } catch (error) {
      console.warn(`shop page ${page} failed: ${error.message}`);
    }
    if (page % 25 === 0 || page === totalPages) {
      console.log(`shop listings progress ${page}/${totalPages}, added=${added}`);
    }
  }
  markRawUrlsDone();
  console.log(`shop listings added ${added} raw rows`);
}

function scrapeListingHtml(html, pageUrl, existing) {
  let added = 0;
  const chunks = html.split(/<div class=["']col-md-4["']>/i).slice(1);
  for (const chunk of chunks) {
    const segment = chunk.split(/<div class=["']col-md-4["']>/i)[0];
    const productUrl = absoluteUrl(extractFirst(segment, /<a[^>]+href=["']([^"']*\/product\/[^"']+)["']/i));
    if (!productUrl || existing.has(productUrl)) continue;
    const title = sanitizeEnglishTitle(extractFirst(segment, /<h3[^>]*>([\s\S]*?)<\/h3>/i));
    const image = absoluteUrl(extractFirst(segment, /<img[^>]+src=["']([^"']+)["']/i));
    const price = parsePrice(extractFirst(segment, /<p[^>]+class=["'][^"']*price[^"']*["'][^>]*>([\s\S]*?)<\/p>/i));
    if (!title || !image || !price) continue;
    const row = {
      title,
      name: shortenName(title, ''),
      product_current_price: price,
      product_old_price: extractOldPrice(segment, price),
      product_discount: '',
      product_url: productUrl,
      product_image_url: image,
      product_seller: 'Top Toys',
      product_availability: segment.includes('Buy Now') ? 'in_stock' : '',
      product_category: 'baby products',
      product_subcategory: '',
      product_unit: extractUnit(title),
      product_weight: extractWeight(title),
      scraping_time: cairoIso(),
      timestamp_timezone: TZ,
      product_brand: extractBrand('', title, []),
      product_ram: extractRam(title),
      product_storage: extractStorage(title),
      _source_category: pageUrl,
    };
    row.product_discount = discount(row.product_old_price, row.product_current_price);
    appendJsonl(RAW_JSONL, row);
    existing.add(productUrl);
    added += 1;
  }
  return added;
}

function extractMaxPage(html) {
  const pages = [...html.matchAll(/\/shop\/page\/(\d+)\/?/gi)].map((m) => Number(m[1])).filter(Boolean);
  return pages.length ? Math.max(...pages) : 1;
}

function markRawUrlsDone() {
  const rawUrls = readExistingRaw();
  const rows = readTodo();
  let changed = false;
  for (const row of rows) {
    if (rawUrls.has(row.url) && row.status !== 'done') {
      row.status = 'done';
      row.error = '';
      changed = true;
    }
  }
  if (changed) writeTodo(rows);
}

async function scrapeOne(todoRow) {
  const html = await fetchText(todoRow.url);
  const ld = extractProductLdJson(html);
  const offer = Array.isArray(ld.offers) ? ld.offers[0] || {} : ld.offers || {};
  const title = cleanText(ld.name || extractFirst(html, /<h1[^>]*>([\s\S]*?)<\/h1>/i));
  const description = cleanText(ld.description || '');
  const productUrl = absoluteUrl(ld.url || todoRow.url);
  const image = absoluteUrl(Array.isArray(ld.image) ? ld.image[0] : ld.image || extractMeta(html, 'og:image'));
  const current = parsePrice(offer.price || extractFirst(html, /<meta[^>]+property=["']product:price:amount["'][^>]+content=["']([^"']+)["']/i));
  const old = extractOldPrice(html, current);
  const categories = extractCategories(html, todoRow.category);
  const tags = extractTags(html);
  const brand = cleanText(extractBrand(html, title, tags));
  const availability = normalizeAvailability(offer.availability || html);
  const unit = extractUnit(`${title} ${description}`);
  const weight = extractWeight(`${title} ${description}`);
  const scrapingTime = cairoIso();

  return {
    title,
    name: shortenName(title, brand),
    product_current_price: current,
    product_old_price: old,
    product_discount: discount(old, current),
    product_url: productUrl,
    product_image_url: image,
    product_seller: cleanText(offer.seller?.name || 'Top Toys'),
    product_availability: availability,
    product_category: standardizeCategory(categories),
    product_subcategory: categories.subcategory,
    product_unit: unit,
    product_weight: weight,
    scraping_time: scrapingTime,
    timestamp_timezone: TZ,
    product_brand: brand,
    product_ram: extractRam(title),
    product_storage: extractStorage(title),
    _source_category: todoRow.category,
  };
}

function extractProductLdJson(html) {
  const scripts = [...html.matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)];
  for (const match of scripts) {
    const raw = decodeHtml(match[1].trim());
    try {
      const parsed = JSON.parse(raw);
      const items = Array.isArray(parsed) ? parsed : [parsed];
      for (const item of items) {
        if (item['@type'] === 'Product') return item;
        if (Array.isArray(item['@graph'])) {
          const product = item['@graph'].find((entry) => entry['@type'] === 'Product');
          if (product) return product;
        }
      }
    } catch (_) {
      continue;
    }
  }
  return {};
}

function extractOldPrice(html, current) {
  const delBlocks = [...html.matchAll(/<del[^>]*>([\s\S]*?)<\/del>/gi)].map((m) => cleanText(m[1]));
  const prices = delBlocks.map(parsePrice).filter((p) => p && (!current || p > current));
  if (prices.length) return Math.max(...prices);
  return '';
}

function extractCategories(html, fallback) {
  const metaMatch = html.match(/Categories:\s*([\s\S]*?)<\/p>/i);
  const labels = [];
  if (metaMatch) {
    for (const match of metaMatch[1].matchAll(/<a[^>]*>([\s\S]*?)<\/a>/gi)) {
      labels.push(cleanText(match[1]));
    }
  }
  if (!labels.length) {
    const classMatch = html.match(/class=["'][^"']*product_cat-[^"']+["']/i);
    if (classMatch) {
      for (const match of classMatch[0].matchAll(/product_cat-([a-z0-9-]+)/gi)) {
        labels.push(slugToTitle(match[1]));
      }
    }
  }
  if (!labels.length && fallback) labels.push(...fallback.split(' > ').filter(Boolean));
  const cleaned = [...new Set(labels.filter(Boolean))];
  return {
    all: cleaned,
    subcategory: cleaned[0] || '',
    broad: cleaned[cleaned.length - 1] || cleaned[0] || '',
  };
}

function extractTags(html) {
  const tags = [];
  const tagMatch = html.match(/Tag:\s*([\s\S]*?)<\/p>/i);
  if (!tagMatch) return tags;
  for (const match of tagMatch[1].matchAll(/<a[^>]*>([\s\S]*?)<\/a>/gi)) {
    tags.push(cleanText(match[1]));
  }
  return tags;
}

function extractBrand(html, title, tags) {
  const brandPatterns = [
    /Brand:\s*<a[^>]*>([\s\S]*?)<\/a>/i,
    /product-tag\/([^/"']+)/i,
  ];
  for (const pattern of brandPatterns) {
    const value = extractFirst(html, pattern);
    if (value) return slugToTitle(value);
  }
  if (tags.length) return slugToTitle(tags[0]);
  const known = [
    'lego', 'chicco', 'farlink', 'banbao', 'fisher price', 'fisher-price', 'playmobil',
    'barbie', 'hot wheels', 'disney', 'hasbro', 'nerf', 'lol', 'mattel', 'pilsan',
    'little tikes', 'vtech', 'babyjem', 'cybex', 'graco', 'joie', 'hauck', 'pigeon',
  ];
  const lower = title.toLowerCase();
  return slugToTitle(known.find((brand) => lower.includes(brand)) || '');
}

function standardizeCategory(categories) {
  const joined = `${categories.broad} ${categories.subcategory} ${categories.all.join(' ')}`.toLowerCase();
  if (/toy|puzzle|doll|lego|play|scooter|bicycle|car|musical|outdoor|beach/.test(joined)) return 'baby products > toys';
  if (/feeding|bottle|nipple|soother|pacifier|sterilizer|cup|plate|spoon|breast/.test(joined)) return 'baby products > feeding';
  if (/fashion|clothes|shoe|sock|costume|blanket|bag|gift|party|balloon/.test(joined)) return 'baby products > fashion';
  if (/health|safty|safety|monitor|thermometer|potty|toilet|gate/.test(joined)) return 'baby products > health and safety';
  if (/nursery|bath|bouncer|rocker|swing|changing/.test(joined)) return 'baby products > nursery and bathing';
  if (/stroller|bugg|car seat|carrier|travel|carrycot/.test(joined)) return 'baby products > on the go';
  return categories.broad ? `baby products > ${categories.broad.toLowerCase()}` : 'baby products';
}

function normalizeRows(rawRows) {
  const seen = new Set();
  const rows = [];
  for (const raw of rawRows) {
    const row = {};
    for (const col of COLUMNS) row[col] = raw[col] ?? '';
    row.title = sanitizeEnglishTitle(row.title);
    row.name = sanitizeEnglishTitle(row.name || row.title) || row.title;
    row.product_url = absoluteUrl(row.product_url);
    row.product_image_url = absoluteUrl(row.product_image_url);
    row.product_current_price = parsePrice(row.product_current_price);
    row.product_old_price = parsePrice(row.product_old_price);
    row.product_discount = discount(row.product_old_price, row.product_current_price);
    row.product_availability = normalizeAvailability(row.product_availability);
    row.timestamp_timezone = TZ;
    row.product_seller = cleanText(row.product_seller || 'Top Toys');
    row.product_category = cleanText(row.product_category || 'baby products');
    row.product_subcategory = cleanText(row.product_subcategory);
    row.product_brand = cleanText(row.product_brand);
    row.product_ram = extractRam(`${row.title} ${row.product_ram}`);
    row.product_storage = extractStorage(`${row.title} ${row.product_storage}`);
    row.product_unit = row.product_unit || extractUnit(row.title);
    row.product_weight = row.product_weight || extractWeight(row.title);

    if (!row.title || !row.product_url || !row.product_current_price || !row.product_image_url) continue;
    if (/undefined|null|test product/i.test(`${row.title} ${row.product_url}`)) continue;
    if (seen.has(row.product_url)) continue;
    seen.add(row.product_url);
    rows.push(row);
  }
  return rows;
}

async function getSitemapChildren(url) {
  const xml = await fetchText(url);
  return [...xml.matchAll(/<loc>\s*([^<]+?)\s*<\/loc>/gi)].map((m) => decodeXml(m[1]));
}

async function getUrlset(url) {
  const xml = await fetchText(url);
  return [...xml.matchAll(/<loc>\s*([^<]+?)\s*<\/loc>/gi)].map((m) => decodeXml(m[1]));
}

function extractProductLinks(html) {
  const links = new Set();
  for (const match of html.matchAll(/href=["']([^"']*\/product\/[^"']+)["']/gi)) {
    const clean = absoluteUrl(match[1].split('#')[0].split('?')[0]);
    if (/\/product\/[^/]+\/?$/i.test(clean)) links.add(clean);
  }
  return [...links];
}

async function fetchText(url, attempt = 1) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  const response = await fetch(url, {
    signal: controller.signal,
    headers: {
      'user-agent': userAgent,
      accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'accept-language': 'en-US,en;q=0.9',
    },
  }).finally(() => clearTimeout(timeout));
  if (!response.ok) {
    if (attempt < 3 && [429, 500, 502, 503, 504].includes(response.status)) {
      await sleep(1000 * attempt);
      return fetchText(url, attempt + 1);
    }
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  return response.text();
}

async function asyncPool(size, items, worker) {
  const executing = new Set();
  for (const item of items) {
    const promise = Promise.resolve().then(() => worker(item));
    executing.add(promise);
    promise.finally(() => executing.delete(promise));
    if (executing.size >= size) await Promise.race(executing);
  }
  await Promise.all(executing);
}

function writeTodo(rows) {
  const csvRows = [['url', 'category', 'status', 'error', 'source']];
  for (const row of rows) csvRows.push([row.url, row.category, row.status || 'pending', row.error || '', row.source || '']);
  fs.writeFileSync(TODO_CSV, csvRows.map(csvLine).join('\n') + '\n', 'utf8');
}

function readTodo() {
  if (!fs.existsSync(TODO_CSV)) return [];
  const lines = fs.readFileSync(TODO_CSV, 'utf8').split(/\r?\n/).filter(Boolean);
  const header = parseCsvLine(lines.shift());
  return lines.map((line) => {
    const values = parseCsvLine(line);
    return Object.fromEntries(header.map((key, i) => [key, values[i] || '']));
  });
}

function updateTodoStatus(todoByUrl, url, status, error) {
  const row = todoByUrl.get(url);
  if (row) {
    row.status = status;
    row.error = error || '';
  }
}

function readExistingRaw() {
  const set = new Set();
  for (const row of readRawRows()) if (row.product_url) set.add(row.product_url);
  return set;
}

function readRawRows() {
  if (!fs.existsSync(RAW_JSONL)) return [];
  return fs.readFileSync(RAW_JSONL, 'utf8')
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line); } catch (_) { return null; }
    })
    .filter(Boolean);
}

function writeClean(rows) {
  const csv = [COLUMNS, ...rows.map((row) => COLUMNS.map((col) => row[col] ?? ''))].map(csvLine).join('\n') + '\n';
  fs.writeFileSync(CLEAN_CSV, csv, 'utf8');
  fs.writeFileSync(CLEAN_JSON, JSON.stringify(rows.map((row) => Object.fromEntries(COLUMNS.map((col) => [col, row[col] ?? '']))), null, 2), 'utf8');
}

function writeReport(rows) {
  const todo = readTodo();
  const report = {
    site: BASE,
    generated_at: cairoIso(),
    timestamp_timezone: TZ,
    target_columns: COLUMNS,
    todo_count: todo.length,
    todo_done: todo.filter((row) => row.status === 'done').length,
    todo_error: todo.filter((row) => row.status === 'error').length,
    clean_rows: rows.length,
    note: 'TopToys sitemap exposes roughly eleven thousand product entries. The scraper dedupes product URLs and exports maximum reachable unique rows; it does not duplicate rows to satisfy an artificial count.',
  };
  fs.writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2), 'utf8');
}

function archiveExports() {
  try {
    if (fs.existsSync(ZIP_PATH)) fs.unlinkSync(ZIP_PATH);
    execFileSync('powershell.exe', [
      '-NoProfile',
      '-Command',
      `Compress-Archive -Path ${psQuote(CLEAN_CSV)},${psQuote(CLEAN_JSON)},${psQuote(TODO_CSV)},${psQuote(REPORT_JSON)} -DestinationPath ${psQuote(ZIP_PATH)} -Force`,
    ], { stdio: 'ignore' });
  } catch (error) {
    console.warn(`zip export skipped: ${error.message}`);
  }
}

function addProduct(map, url, category, source) {
  const clean = absoluteUrl(url.split('#')[0].split('?')[0]);
  const existing = map.get(clean);
  if (existing) {
    if (!existing.category && category) existing.category = category;
    if (!existing.source.includes(source)) existing.source += `+${source}`;
    return;
  }
  map.set(clean, { url: clean, category, status: 'pending', error: '', source });
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith('--')) continue;
    const key = argv[i].slice(2);
    const next = argv[i + 1];
    out[key] = next && !next.startsWith('--') ? argv[++i] : true;
  }
  return out;
}

function parsePrice(value) {
  if (value === '' || value === null || value === undefined) return '';
  if (typeof value === 'number') return Number.isFinite(value) ? Number(value.toFixed(2)) : '';
  const match = decodeHtml(String(value)).replace(/,/g, '').match(/\d+(?:\.\d+)?/);
  if (!match) return '';
  const num = Number(match[0]);
  return Number.isFinite(num) ? num : '';
}

function discount(oldPrice, currentPrice) {
  const oldNum = Number(oldPrice);
  const currentNum = Number(currentPrice);
  if (!oldNum || !currentNum || oldNum <= currentNum) return '';
  return Number((((oldNum - currentNum) / oldNum) * 100).toFixed(3));
}

function normalizeAvailability(value) {
  const text = String(value || '').toLowerCase();
  if (text === 'out_of_stock') return 'out_of_stock';
  if (text === 'in_stock') return 'in_stock';
  if (text.includes('outofstock') || text.includes('out-of-stock') || text.includes('out of stock') || text.includes('schema.org/outofstock')) return 'out_of_stock';
  if (text.includes('instock') || text.includes('in stock') || text.includes('available') || text.includes('schema.org/instock')) return 'in_stock';
  return '';
}

function extractRam(text) {
  const match = String(text || '').match(/\b(\d{1,3}\s?GB)\s*(?:RAM|Memory)?\b/i);
  return match && /ram|memory/i.test(text.slice(Math.max(0, match.index - 20), match.index + 30)) ? match[1].replace(/\s+/g, '').toUpperCase() : '';
}

function extractStorage(text) {
  const match = String(text || '').match(/\b(\d{2,4}\s?(?:GB|TB)(?:\s?SSD)?)\b/i);
  if (!match) return '';
  const around = text.slice(Math.max(0, match.index - 20), match.index + 50);
  return /ssd|storage|rom|hdd|flash|disk|\d+\s?(?:gb|tb)\s?ssd/i.test(around) ? match[1].replace(/\s+/g, '').toUpperCase() : '';
}

function extractUnit(text) {
  const match = String(text || '').match(/\b(\d+(?:\.\d+)?\s?(?:pcs|pieces|pc|pack|packs|set|sets|ml|l|g|kg|oz))\b/i);
  return match ? match[1].replace(/\s+/g, ' ').trim() : '';
}

function extractWeight(text) {
  const match = String(text || '').match(/\b(\d+(?:\.\d+)?\s?(?:kg|g|ml|l|oz))\b/i);
  return match ? match[1].replace(/\s+/g, ' ').trim() : '';
}

function shortenName(title, brand) {
  let name = cleanText(title);
  if (brand) name = name.replace(new RegExp(`^${escapeRegex(brand)}\\s+`, 'i'), '');
  name = name.replace(/\s*[-|,]?\s*(?:red|blue|green|yellow|black|white|pink|purple|orange|grey|gray|brown)\b/ig, '');
  return cleanText(name);
}

function categoryFromUrl(url) {
  const parts = new URL(url).pathname.split('/').filter(Boolean);
  const idx = parts.indexOf('product-category');
  return parts.slice(idx + 1).filter((part) => part !== 'all').map(slugToTitle).join(' > ');
}

function joinUrl(base, suffix) {
  return base.replace(/\/?$/, '/') + suffix;
}

function absoluteUrl(value) {
  if (!value) return '';
  try { return new URL(decodeHtml(String(value).trim()), BASE).href; } catch (_) { return ''; }
}

function extractMeta(html, property) {
  return extractFirst(html, new RegExp(`<meta[^>]+property=["']${escapeRegex(property)}["'][^>]+content=["']([^"']+)["']`, 'i'));
}

function extractFirst(text, regex) {
  const match = String(text || '').match(regex);
  return match ? cleanText(match[1]) : '';
}

function cleanText(value) {
  return decodeHtml(String(value || '').replace(/<[^>]*>/g, ' '))
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function sanitizeEnglishTitle(value) {
  const text = cleanText(value).replace(/[\u0600-\u06FF]+/g, '').replace(/\s+/g, ' ').trim();
  return /[A-Za-z0-9]/.test(text) ? text : '';
}

function decodeHtml(value) {
  return String(value || '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ');
}

function decodeXml(value) {
  return decodeHtml(value);
}

function slugToTitle(value) {
  return cleanText(String(value || '').replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()));
}

function csvLine(values) {
  return values.map((value) => {
    const text = value === null || value === undefined ? '' : String(value);
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }).join(',');
}

function parseCsvLine(line) {
  const out = [];
  let current = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (quoted) {
      if (char === '"' && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        current += char;
      }
    } else if (char === ',') {
      out.push(current);
      current = '';
    } else if (char === '"') {
      quoted = true;
    } else {
      current += char;
    }
  }
  out.push(current);
  return out;
}

function appendJsonl(file, row) {
  fs.appendFileSync(file, `${JSON.stringify(row)}\n`, 'utf8');
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function cairoIso() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(new Date()).reduce((acc, part) => {
    acc[part.type] = part.value;
    return acc;
  }, {});
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+03:00`;
}

function psQuote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
