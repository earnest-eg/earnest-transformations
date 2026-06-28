# E-Commerce Analytics Dashboard - dbt Project

## Overview
This repository contains the dbt (data build tool) project for the E-Commerce Analytics Dashboard. It transforms raw scraped data into a clean, dimensional data model suitable for analytical queries and business intelligence reporting. 

The project leverages a star schema architecture to organize e-commerce product listings, sellers, and temporal data, empowering downstream applications to perform aggregations and slice-and-dice operations.

## Data Architecture
The data models are organized into specific layers to separate data preparation from business logic.

### 1. Staging (`models/staging/`)
The staging layer connects to the raw data sources. It normalizes column names, applies initial data type casting, and acts as the entry point for all upstream data.

### 2. Marts (`models/marts/`)
The marts layer implements the core business logic and dimensional modeling. It includes:
- **Fact Table (`fact_product`)**: Contains the core measurable metrics related to product pricing, discounts, and availability.
- **Dimension Tables**:
  - `dim_product`: Captures product attributes such as brand, category, subcategory, and specifications.
  - `dim_seller`: Captures seller information and platform categorization.
  - `dim_date`: A calendar dimension for analyzing trends over specific days, months, and seasons.
  - `dim_time`: A time-of-day dimension for analyzing intraday patterns.

### 3. Semantic Layer (`models/semantic/`)
The semantic layer utilizes dbt MetricFlow to define standardized metrics and dimensions, ensuring a single source of truth for business definitions.
- **Semantic Models**: Map the dimensional models to entities, dimensions, and measures.
- **Metrics**: Define specific calculations (e.g., Average Product Price, Total Discount Amount) that can be queried directly via the dbt Semantic Layer.
- **Time Spine**: Provides the foundational temporal spine required by MetricFlow for accurate time-series aggregations.

## Prerequisites
- Python 3.8 or higher
- dbt-core
- Appropriate dbt adapter (e.g., dbt-snowflake, dbt-postgres) depending on the target data warehouse

## Setup and Execution

1. **Install dependencies**
   Ensure your dbt environment is configured and dependencies are installed:
   ```bash
   dbt deps
   ```

2. **Run the models**
   Execute the data transformations to build the staging and mart tables:
   ```bash
   dbt run
   ```

3. **Test the models**
   Run the defined tests (unique, not_null, relationship, and accepted values) to ensure data integrity:
   ```bash
   dbt test
   ```

4. **Generate documentation**
   Compile and serve the project documentation:
   ```bash
   dbt docs generate
   dbt docs serve
   ```

## Development Guidelines
- Ensure all new models include corresponding schema tests in `schema.yml`.
- Document new columns and models clearly.
- Follow the established naming conventions for files and fields.
- Update the semantic models and metrics when adding new measures to the fact table.
