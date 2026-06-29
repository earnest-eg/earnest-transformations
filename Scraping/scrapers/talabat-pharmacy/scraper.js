import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const START_URL =
  process.env.START_URL ||
  "https://www.talabat.com/egypt/pharmacies/7808/el-shorouk-military-area";
const HEADLESS = (process.env.HEADLESS || "true").toLowerCase() !== "false";
const MAX_PHARMACIES = Number(process.env.MAX_PHARMACIES || 0);
const MAX_CATEGORIES_PER_PHARMACY = Number(process.env.MAX_CATEGORIES_PER_PHARMACY || 0);
const MAX_PRODUCTS_PER_CATEGORY = Number(process.env.MAX_PRODUCTS_PER_CATEGORY || 0);
const DELAY_MS = Number(process.env.DELAY_MS || 900);
const SCRAPE_PRODUCT_DETAILS =
  (process.env.SCRAPE_PRODUCT_DETAILS || "false").toLowerCase() === "true";
const OUT_DIR = path.resolve("data");

const COLUMNS = [
  "title",
  "current_price",
  "old_price",
  "discount",
  "url",
  "category",
  "name",
  "Specifications",
  "img_URL",
  "time",
  "place",
];

const CATEGORY_TEXT_RE =
  /category|categories|menu|shop|products|personal|baby|medicine|vitamin|health|beauty|skin|hair|care|women|men|offers/i;

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({
    locale: "en-US",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
  });

  try {
    const page = await context.newPage();
    const place = await discoverPharmacies(page, START_URL);

    const pharmacies = limitItems(await readJson("pharmacies_todo.json", []), MAX_PHARMACIES);
    for (const pharmacy of pharmacies) {
      if (pharmacy.status === "done") continue;
      const pharmacyComplete = await runPharmacy(context, pharmacy, place);
      pharmacy.status = pharmacyComplete ? "done" : "partial";
      pharmacy.finished_at = new Date().toISOString();
      await writeJson("pharmacies_todo.json", pharmacies);
    }

    await exportProducts();
  } finally {
    await browser.close();
  }
}

async function discoverPharmacies(page, url) {
  await goto(page, url);
  await scrollToBottom(page);
  const place = await page.locator("h1").first().textContent().catch(() => "");
  const links = await page.locator("a").evaluateAll((anchors) =>
    anchors
      .map((a) => ({
        name: (a.textContent || "").replace(/\s+/g, " ").trim(),
        url: a.href,
      }))
      .filter((a) => /\/egypt\/pharmacy\//.test(a.url))
  );

  const existing = await readJson("pharmacies_todo.json", []);
  const merged = mergeByUrl(existing, links.map((link) => ({
    ...link,
    status: existing.find((item) => item.url === link.url)?.status || "pending",
  })));
  await writeJson("pharmacies_todo.json", merged);
  console.log(`Discovered ${merged.length} pharmacies`);
  return clean(place).replace(/^Pharmacy Delivery from Local Stores Near Me in\s+/i, "");
}

async function runPharmacy(context, pharmacy, place) {
  const page = await context.newPage();
  const jsonPayloads = [];
  page.on("response", async (response) => {
    const contentType = response.headers()["content-type"] || "";
    if (!contentType.includes("json")) return;
    try {
      jsonPayloads.push({ url: response.url(), body: await response.json() });
    } catch {
      // Ignore non-JSON bodies incorrectly labeled as JSON.
    }
  });

  try {
    await goto(page, toGroceryUrl(pharmacy.url));
    await closePopups(page);
    await scrollToBottom(page);

    const pharmacyMeta = await getPharmacyMeta(page, pharmacy, place);
    const categories = await discoverCategories(page, jsonPayloads, pharmacy, pharmacyMeta);
    const categoryQueue = await upsertCategories(categories);
    const knownStatus = new Map(
      categoryQueue
        .filter((item) => item.pharmacy_url === pharmacy.url)
        .map((item) => [item.category, item.status])
    );
    for (const category of categories) {
      category.status = knownStatus.get(category.category) || category.status;
    }

    const selectedCategories = limitItems(categories, MAX_CATEGORIES_PER_PHARMACY);
    for (const category of selectedCategories) {
      if (category.status === "done") continue;
      const products = await scrapeCategory(page, category, pharmacyMeta, jsonPayloads);
      await upsertProducts(products);
      await exportProducts();
      category.status = "done";
      category.finished_at = new Date().toISOString();
      await upsertCategories([category]);
      await sleep(DELAY_MS);
    }
    return selectedCategories.length === categories.length && categories.every((item) => item.status === "done");
  } finally {
    await page.close();
  }
}

async function discoverCategories(page, jsonPayloads, pharmacy, pharmacyMeta) {
  const domCategories = await page.locator('a[data-testid="category-item-container"], a[href*="/grocery/"]').evaluateAll(
    (nodes) =>
      nodes
        .map((node) => {
          const text = (node.textContent || "").replace(/\s+/g, " ").trim();
          const href = node.href || "";
          return { category: text, url: href || location.href };
        })
        .filter((item) => item.category && item.category.length < 80)
        .filter((item) => item.url.includes("/egypt/grocery/"))
        .filter((item) => new RegExp("category-item-container|medicines|personal|baby|vitamin|health|beauty|skin|hair|care|women|men|offers", "i").test(item.category))
  );

  const nextCategories = await extractCategoriesFromNextData(page, pharmacy, pharmacyMeta);

  const jsonCategories = [];
  for (const payload of jsonPayloads) {
    walk(payload.body, (node) => {
      if (!node || typeof node !== "object") return;
      const name = firstString(node, ["name", "title", "categoryName", "displayName"]);
      if (!name || name.length > 80) return;
      const id = firstString(node, ["id", "categoryId", "menuCategoryId", "slug"]);
      const url = firstString(node, ["url", "href", "deeplink"]) || pharmacy.url;
      if (/product/i.test(name)) return;
      if ((CATEGORY_TEXT_RE.test(name) || id) && !/^careers$/i.test(name)) {
        jsonCategories.push({ category: name, url });
      }
    });
  }

  const categories = mergeByKey([...nextCategories, ...domCategories, ...jsonCategories], "category")
    .map((item) => ({
      pharmacy: pharmacy.name,
      pharmacy_url: pharmacy.url,
      category: clean(item.category),
      url: absolutize(item.url || pharmacy.url, pharmacy.url),
      status: "pending",
      time: pharmacyMeta.time,
      place: pharmacyMeta.place,
    }))
    .filter((item) => item.category);

  if (categories.length === 0) {
    categories.push({
      pharmacy: pharmacy.name,
      pharmacy_url: pharmacy.url,
      category: "All products",
      url: pharmacy.url,
      status: "pending",
      time: pharmacyMeta.time,
      place: pharmacyMeta.place,
    });
  }

  console.log(`${pharmacy.name}: discovered ${categories.length} categories`);
  return categories;
}

async function extractCategoriesFromNextData(page, pharmacy, pharmacyMeta) {
  const baseUrl = toGroceryUrl(pharmacy.url).split("?")[0];
  const aid = new URL(pharmacy.url).searchParams.get("aid") || new URL(START_URL).pathname.split("/")[3] || "";
  const categories = await page
    .locator("#__NEXT_DATA__")
    .textContent({ timeout: 5000 })
    .then((text) => {
      const data = JSON.parse(text);
      return data?.props?.pageProps?.initialState?.categories || [];
    })
    .catch(() => []);

  const rows = [];
  for (const category of categories) {
    const subCategories = Array.isArray(category.subCategories) ? category.subCategories : [];
    if (subCategories.length === 0) {
      rows.push({
        category: clean(category.name),
        url: `${baseUrl}/${category.slug}${aid ? `?aid=${aid}` : ""}`,
      });
      continue;
    }

    for (const subCategory of subCategories) {
      rows.push({
        category: `${clean(category.name)} > ${clean(subCategory.name)}`,
        url: `${baseUrl}/${category.slug}/${subCategory.slug}${aid ? `?aid=${aid}` : ""}`,
        status: "pending",
        time: pharmacyMeta.time,
        place: pharmacyMeta.place,
      });
    }
  }
  return rows;
}

async function scrapeCategory(page, category, pharmacyMeta, jsonPayloads) {
  if (page.url() !== category.url) {
    await goto(page, category.url);
    await closePopups(page);
  }

  await clickCategoryIfVisible(page, category.category);
  await scrollToBottom(page);

  const products = [
    ...(await extractProductsFromDom(page, category, pharmacyMeta)),
    ...extractProductsFromJson(jsonPayloads, category, pharmacyMeta),
  ];

  const unique = mergeByKey(products.filter((product) => product.title), "url_title_key");
  let limited =
    MAX_PRODUCTS_PER_CATEGORY > 0 ? unique.slice(0, MAX_PRODUCTS_PER_CATEGORY) : unique;
  if (SCRAPE_PRODUCT_DETAILS) {
    limited = await enrichProductDetails(page, limited);
  }
  console.log(`${category.pharmacy} / ${category.category}: ${limited.length} products`);
  return limited;
}

async function enrichProductDetails(page, products) {
  const enriched = [];
  for (const product of products) {
    try {
      await goto(page, product.url);
      const details = await page.evaluate(() => {
        const bodyText = document.body.innerText.replace(/\s+/g, " ").trim();
        const metaDescription =
          document.querySelector('meta[name="description"]')?.getAttribute("content") || "";
        const headingText = [...document.querySelectorAll("h1, h2, h3")]
          .map((node) => node.textContent?.replace(/\s+/g, " ").trim())
          .filter(Boolean)
          .join(" | ");
        return {
          specifications: metaDescription || headingText || bodyText.slice(0, 500),
        };
      });
      enriched.push({
        ...product,
        Specifications: product.Specifications || details.specifications,
        detail_status: "done",
      });
      await sleep(DELAY_MS);
    } catch (error) {
      enriched.push({
        ...product,
        detail_status: "failed",
        detail_error: error.message,
      });
    }
  }
  return enriched;
}

async function extractProductsFromDom(page, category, pharmacyMeta) {
  return page.locator('a[data-testid="grocery-item-link-nofollow"]').evaluateAll(
    (nodes, context) => {
      const rows = [];
      for (const node of nodes) {
        const title = (node.querySelector('[data-test="item-name"]')?.textContent || "")
          .replace(/\s+/g, " ")
          .trim();
        const currentPrice = (node.querySelector('[data-testid="price"]')?.textContent || "")
          .replace(/\s+/g, " ")
          .trim();
        const oldPrice = (
          node.querySelector('[data-testid*="old" i], [class*="old" i], del, s')?.textContent || ""
        )
          .replace(/\s+/g, " ")
          .trim();
        const discount = (
          node.querySelector('[data-testid*="discount" i], [class*="discount" i], .tag')?.textContent || ""
        )
          .replace(/\s+/g, " ")
          .trim();
        const img = node.querySelector("img")?.src || "";
        const href = node.href || node.querySelector("a")?.href || location.href;
        if (!title || !currentPrice) continue;
        rows.push({
          title,
          current_price: currentPrice,
          old_price: oldPrice,
          discount,
          url: href,
          category: context.category.category,
          name: context.pharmacyMeta.name,
          Specifications: "",
          img_URL: img,
          time: context.pharmacyMeta.time,
          place: context.pharmacyMeta.place,
          url_title_key: `${href}|${title}`,
        });
      }
      return rows;
    },
    { category, pharmacyMeta }
  );
}

function extractProductsFromJson(jsonPayloads, category, pharmacyMeta) {
  const products = [];
  for (const payload of jsonPayloads) {
    walk(payload.body, (node) => {
      if (!looksLikeProduct(node)) return;
      const title = firstString(node, ["title", "name", "productName", "displayName"]);
      const currentPrice = firstValue(node, ["current_price", "currentPrice", "price", "unitPrice", "sellingPrice"]);
      const oldPrice = firstValue(node, ["old_price", "oldPrice", "originalPrice", "strikeThroughPrice", "wasPrice"]);
      const discount = firstValue(node, ["discount", "discountText", "discountPercentage", "offerText"]);
      const url = absolutize(firstString(node, ["url", "href", "deeplink"]) || category.url, category.url);
      const img = firstString(node, ["image", "imageUrl", "image_url", "thumbnail", "photoUrl"]);
      products.push({
        title: clean(title),
        current_price: formatValue(currentPrice),
        old_price: formatValue(oldPrice),
        discount: formatValue(discount),
        url,
        category: category.category,
        name: pharmacyMeta.name,
        Specifications: firstString(node, ["specifications", "description", "subtitle"]) || "",
        img_URL: img || "",
        time: pharmacyMeta.time,
        place: pharmacyMeta.place,
        url_title_key: `${url}|${clean(title)}`,
      });
    });
  }
  return products;
}

async function getPharmacyMeta(page, pharmacy, place) {
  const heading = await page.locator("h1").first().textContent().catch(() => pharmacy.name);
  const body = await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
  const time = (body.match(/\b\d+\s*-\s*\d+\s*mins?\b|\b\d+\s*mins?\b/i) || [""])[0];
  return {
    name: clean(heading || pharmacy.name),
    time: clean(time || pharmacy.name.match(/\d+\s*mins?/i)?.[0] || ""),
    place: clean(place || ""),
  };
}

async function clickCategoryIfVisible(page, categoryName) {
  const locator = page.getByText(categoryName, { exact: true }).first();
  if (await locator.isVisible().catch(() => false)) {
    await locator.click().catch(() => {});
    await sleep(DELAY_MS);
  }
}

async function closePopups(page) {
  const candidates = ["Accept", "I agree", "Got it", "Close", "No thanks", "Later"];
  for (const text of candidates) {
    const button = page.getByRole("button", { name: new RegExp(text, "i") }).first();
    if (await button.isVisible().catch(() => false)) {
      await button.click().catch(() => {});
      await sleep(250);
    }
  }
}

async function scrollToBottom(page) {
  let previousHeight = 0;
  for (let i = 0; i < 18; i += 1) {
    const height = await page.evaluate(() => document.body.scrollHeight);
    if (height === previousHeight) break;
    previousHeight = height;
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await sleep(DELAY_MS);
  }
}

async function goto(page, url) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
  await sleep(DELAY_MS);
}

async function upsertCategories(items) {
  const existing = await readJson("categories_todo.json", []);
  const merged = mergeCategories(existing, items);
  await writeJson("categories_todo.json", merged);
  return merged;
}

async function upsertProducts(items) {
  const existing = await readJson("products.json", []);
  await writeJson("products.json", mergeByKey([...existing, ...items], "url_title_key"));
}

async function exportProducts() {
  const products = await readJson("products.json", []);
  await writeJson(
    "products_todo.json",
    products.map((product) => ({
      url: product.url,
      title: product.title,
      category: product.category,
      name: product.name,
      status: product.detail_status || "pending",
    }))
  );
  const rows = products.map((product) => COLUMNS.map((column) => product[column] || ""));
  const csv = [COLUMNS, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n");
  await fs.writeFile(path.join(OUT_DIR, "products.csv"), csv, "utf8");
  console.log(`Exported ${products.length} products`);
}

async function readJson(file, fallback) {
  try {
    return JSON.parse(await fs.readFile(path.join(OUT_DIR, file), "utf8"));
  } catch {
    return fallback;
  }
}

async function writeJson(file, value) {
  await fs.writeFile(path.join(OUT_DIR, file), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function mergeByUrl(existing, incoming) {
  return mergeByKey([...existing, ...incoming], "url");
}

function mergeByKey(items, key) {
  const map = new Map();
  for (const item of items) {
    const mapKey =
      key === "pharmacy_url_category_key"
        ? `${item.pharmacy_url}|${item.category}`
        : item[key] || JSON.stringify(item);
    map.set(mapKey, { ...map.get(mapKey), ...item });
  }
  return [...map.values()];
}

function mergeCategories(existing, incoming) {
  const map = new Map();
  for (const item of [...existing, ...incoming]) {
    const key = `${item.pharmacy_url}|${item.category}`;
    const previous = map.get(key) || {};
    const merged = { ...previous, ...item };
    if (previous.status === "done" && item.status === "pending") merged.status = "done";
    map.set(key, merged);
  }
  return [...map.values()];
}

function looksLikeProduct(node) {
  if (!node || typeof node !== "object" || Array.isArray(node)) return false;
  const title = firstString(node, ["title", "name", "productName", "displayName"]);
  if (!title || title.length > 180) return false;
  return ["price", "currentPrice", "unitPrice", "sellingPrice", "image", "imageUrl"].some(
    (key) => Object.prototype.hasOwnProperty.call(node, key)
  );
}

function walk(value, visitor) {
  visitor(value);
  if (Array.isArray(value)) {
    for (const item of value) walk(item, visitor);
  } else if (value && typeof value === "object") {
    for (const item of Object.values(value)) walk(item, visitor);
  }
}

function firstString(object, keys) {
  const value = firstValue(object, keys);
  return typeof value === "string" ? clean(value) : "";
}

function firstValue(object, keys) {
  if (!object || typeof object !== "object") return "";
  for (const key of keys) {
    if (object[key] !== undefined && object[key] !== null && object[key] !== "") return object[key];
  }
  return "";
}

function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function formatValue(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") return clean(value.amount ?? value.value ?? JSON.stringify(value));
  return clean(value);
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function absolutize(url, baseUrl) {
  try {
    return new URL(url, baseUrl).toString();
  } catch {
    return baseUrl;
  }
}

function toGroceryUrl(url) {
  return url.replace("/egypt/pharmacy/", "/egypt/grocery/");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function limitItems(items, limit) {
  return limit > 0 ? items.slice(0, limit) : items;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
