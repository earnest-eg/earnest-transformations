# Sigma Computer Scraper

![Node.js](https://img.shields.io/badge/Node.js-20%2B-339933)
![Sample](https://img.shields.io/badge/Sample-10_cleaned_rows-blue)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Overview

Computers, components, gaming, and electronics.

This is an independently runnable project in the **Egypt E-commerce Web Scrapers** collection. It contains one final scraper and a cleaned sample that demonstrates the shared output contract.

## Capabilities

- Structured product names, prices, categories, and URLs
- Sitemap-based URL discovery
- Asynchronous request processing
- Paginated catalog traversal
- Duplicate detection
- CSV export
- JSON processing or export

Capabilities are detected from the current source. Website changes may affect runtime behavior.

## Project files

| File | Purpose |
|---|---|
| **scraper.js** | Final scraper entry point |
| **sample_data.csv** | 10 cleaned and deduplicated example products |
| **README.md** | Setup, usage, quality, and maintenance guidance |

## Technology

- **Runtime:** Node.js 20+
- **Detected stack:** Fetch API
- **Output model:** normalized retail product records

## Setup

Run this setup from the repository root:

~~~powershell
npm install
npx playwright install chromium
~~~

Chromium is only required when the scraper uses browser automation.

## Run

~~~powershell
cd scrapers/sigma
node scraper.js
~~~

Run from this directory so relative output paths resolve correctly.

## Sample data

The included **sample_data.csv** contains exactly 10 unique cleaned records:

~~~text
name, price, old_price, discount, category, brand,
url, image_url, availability, seller
~~~

The sample demonstrates structure only. Prices, promotions, stock, and URLs may differ from the live website.

## Pre-run checklist

1. Review target URLs, locale, and store settings in **scraper.js**.
2. Check delay, concurrency, timeout, retry, and browser settings.
3. Confirm output paths and available disk space.
4. Start with a small page or product limit when supported.
5. Inspect the first records before starting a complete run.
6. Stop on access-denied or rate-limit responses.

## Data-quality checklist

- Product name and current price are present.
- Prices are numeric and use the expected currency.
- Product and image URLs are valid HTTP or HTTPS links.
- Duplicate products and variants are handled intentionally.
- Arabic and English text remains UTF-8 encoded.
- Discounts agree with current and old prices when both exist.

## Maintenance

If extraction fails, check the HTTP status, content type, and final URL first. Compare current HTML or API fields with the scraper selectors and mappings, then retest with a small limit.

## Responsible use

Collect only public data you are permitted to access. Review the target website's terms and robots policy, keep request rates low, and do not bypass authentication, CAPTCHA, paywalls, or other access controls.

## Documentation

- [Collection documentation](../../DOCUMENTATION.md)
- [Main project README](../../README.md)
- [MIT License](../../LICENSE)
