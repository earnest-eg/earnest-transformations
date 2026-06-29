# Web Scraping Collection - Technical Documentation

## 1. Overview

This repository contains 39 independent web scrapers for Egyptian retail and e-commerce websites. It is a source-focused collection intended for learning, maintenance, and controlled data collection.

Each scraper project contains:

- One final Python or JavaScript scraper
- One cleaned CSV sample containing 10 products
- One project README with basic run instructions

Historical versions, debug tools, test scripts, cached pages, full datasets, archives, browser profiles, and generated logs are intentionally excluded.

## 2. Repository structure

```text
.
├── scrapers/
│   ├── ariika/
│   │   ├── scraper.py
│   │   ├── sample_data.csv
│   │   └── README.md
│   ├── dream2000/
│   │   ├── scraper.js
│   │   ├── sample_data.csv
│   │   └── README.md
│   └── ...
├── .gitignore
├── DOCUMENTATION.md
├── README.md
├── package.json
└── requirements.txt
```

The scrapers are independent. Running one project does not automatically run the others.

### Design principles

- **Isolation:** each retailer is a self-contained project.
- **Single entry point:** each folder exposes only `scraper.py` or `scraper.js`.
- **Consistent examples:** every project includes the same cleaned sample schema.
- **Source-only repository:** generated catalogs, caches, and browser artifacts stay outside Git.
- **Explicit operation:** scrapers run individually so operators can review target-specific settings first.

### Data flow

```text
Target website or API
        |
        v
Discovery and pagination
        |
        v
Product extraction
        |
        v
Normalization and deduplication
        |
        v
CSV or JSON output
        |
        v
Quality validation
```

The exact discovery and extraction stages vary by retailer. Some scripts consume public APIs or sitemaps, while others render pages in a browser.

## 3. Supported projects

| Project | Project | Project |
|---|---|---|
| Ariika | Baby Island | Bashrety |
| Btech | Cairo Sales | Chicco |
| Compumarts | Cstore | Decathlon |
| Dokkan Tech | Dream2000 | Elfar |
| Elghazawy | Ennap | EVA |
| Fresh | Go Sport | Gourmet |
| HyperOne | IKEA | Intersport |
| Kimostore | Mazaya | Meercato |
| Metro | Mobiletest | Noon |
| Raya | Samir Aly | Seoudi |
| Sigma | Source Beauty | Talabat |
| Talabat Pharmacy | Talabat Pharmacy 2 | The Beauty |
| TopToys | Tradeline | Unionaire |

## 4. Requirements

### Python projects

- Python 3.11 or newer
- Internet access
- Chromium for Playwright-based projects

Install the shared Python environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

### JavaScript projects

- Node.js 20 or newer
- npm
- Internet access

```powershell
npm install
npx playwright install chromium
```

Not every scraper uses every shared dependency. The root dependency files provide a convenient common environment for the collection.

## 5. Running a scraper

Read the README inside the selected project before running it. Then execute the scraper from its own folder so relative output paths work correctly.

Python example:

```powershell
cd scrapers/ariika
python scraper.py
```

JavaScript example:

```powershell
cd scrapers/dream2000
node scraper.js
```

Before a full run, inspect the constants and command-line options in the script. Confirm:

- Target URL and locale
- Output directory and filename
- Request delay and concurrency
- Product or page limits
- Resume or checkpoint behavior
- Browser headless setting

## 6. Sample data

Every project includes `sample_data.csv` with exactly 10 cleaned, unique product records. The samples demonstrate the expected normalized format; they are not complete or live product catalogs.

### Standard schema

| Column | Type | Description |
|---|---|---|
| `name` | text | Clean product name |
| `price` | decimal text | Current price with currency symbols removed |
| `old_price` | decimal text | Previous price when available |
| `discount` | decimal text | Discount value or percentage reported by the source |
| `category` | text | Product category or category path |
| `brand` | text | Product brand when available |
| `url` | URL | HTTP or HTTPS product page |
| `image_url` | URL | HTTP or HTTPS product image |
| `availability` | text | Source stock or availability value |
| `seller` | text | Seller, retailer, market, or pharmacy |

Optional fields may be blank when the source dataset did not provide a reliable value.

### Cleaning rules

The included samples were prepared using these rules:

1. Require a non-empty product name and current price.
2. Decode HTML entities and remove control characters.
3. Collapse repeated whitespace and trim text.
4. Normalize numeric prices and discounts without currency symbols.
5. Keep only valid HTTP or HTTPS URLs.
6. Remove duplicates using the product URL, or the name and price when no URL exists.
7. Limit the final sample to 10 records per project.

## 7. Scraping approaches

The collection contains several implementation styles:

- HTTP clients for public HTML, XML, and JSON endpoints
- Beautiful Soup or lxml for static HTML parsing
- Playwright or Selenium for JavaScript-rendered pages
- Async requests for higher-throughput collection
- Sitemap discovery for category and product URLs
- Storefront, GraphQL, or public product APIs where available

The selected approach reflects how each website behaved when the scraper was created. A site redesign or API change may require a different approach.

## 8. Output and source control

Scrapers may create CSV, JSON, HTML, log, ZIP, or checkpoint files. Generated files are ignored by the root `.gitignore`, except for the curated `sample_data.csv` files.

Recommended output practices:

- Write generated data outside the source directory when possible.
- Use UTF-8 encoding.
- Preserve a raw export before applying transformations.
- Deduplicate using a stable product URL, SKU, or source identifier.
- Record the scrape timestamp and source when maintaining production datasets.
- Do not commit large datasets or browser caches to Git.

## 9. Data-quality checklist

After running a scraper, verify:

- Product count is plausible for the target scope.
- Product names and URLs are present.
- Prices are numeric and use the expected currency.
- Old prices are not lower than current prices unless the source explicitly reports that state.
- Discounts agree with current and old prices.
- URLs and image URLs are valid.
- Categories and brands are not shifted into incorrect columns.
- Duplicate products and variants are handled intentionally.
- CSV and JSON exports contain the same records when both are produced.
- Arabic and English text remains valid UTF-8.

## 10. Reliability and maintenance

Web scrapers require ongoing maintenance because websites change without notice. Common failure causes include:

- Modified HTML selectors
- Renamed or protected API endpoints
- Pagination changes
- Bot protection, rate limits, or CAPTCHA
- Required cookies, location, or store selection
- Expired product URLs
- Changed JSON response structures
- Browser or dependency updates

When a scraper fails:

1. Run a small request against one known product or category.
2. Check the HTTP status, response content type, and final URL.
3. Compare the current response with the fields expected by the parser.
4. Update selectors or response-field mappings.
5. Retest with a small limit.
6. Validate the output before running the full scrape.

## 11. Responsible use

Use these scripts only for public data you are permitted to access.

- Review the website's terms of service and robots policy.
- Use an identifiable, appropriate user agent where possible.
- Keep delays and concurrency at a respectful level.
- Stop when the website returns rate-limit or access-denied responses.
- Do not bypass authentication, CAPTCHA, paywalls, or technical restrictions.
- Do not collect personal, private, or restricted information.
- Do not publish copyrighted images or full datasets without permission.

The repository does not grant permission to scrape any website. Compliance remains the operator's responsibility.

## 12. Security

Never place credentials directly in scraper source code. Use environment variables for secrets:

```powershell
$env:API_KEY = "your-value"
python scraper.py
```

Before committing:

- Review `git status`.
- Check for API keys, cookies, bearer tokens, proxy credentials, and personal paths.
- Confirm that generated outputs remain ignored.
- Never commit `.env`, browser profiles, session storage, or authentication cookies.

## 13. Contributing

Keep contributions consistent with the simplified structure:

1. One final scraper per project folder.
2. One project README.
3. One cleaned `sample_data.csv` containing exactly 10 records.
4. No generated full datasets, caches, or archives.
5. Clear rate limiting, timeout handling, and error handling.
6. UTF-8 output and deterministic column names.

When replacing a scraper, update its sample data and README in the same change.

## 14. Known limitations

- The scrapers have not all been live-tested against current websites in one environment.
- Some target websites require location, store, browser, or session configuration.
- Shared dependency files may include packages unused by an individual scraper.
- Sample data reflects existing local exports and may not match current website prices.
- Empty optional sample fields indicate unavailable source values, not extraction errors.

## 15. License

This project is available under the MIT License. See [LICENSE](LICENSE) for the complete terms.
