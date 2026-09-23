# Architecture Overview

This page explains how the project is organized and how the main pieces work together.
It is written for both technical and non-technical readers.

## What this project does

The project provides an API that helps formulate fish feed recipes based on:

- nutritional targets,
- ingredient composition data,
- user-provided prices,
- and safety/quality constraints.

## Main building blocks

- `fasa_api/`: API layer (receives requests and returns responses)
- `fasa_core/`: core logic (data loading, constraints, inclusion limits, optimization, validation)
- `data/`: reference CSV files used by the core logic
- `.github/workflows/`: CI, deployment, and release automation

## How a typical request flows

1. A client sends a request to the API (for example `POST /formulate`).
2. The API validates input and checks authorization (when enabled).
3. The API calls the core engine to run calculations.
4. The API returns a structured result (`optimal`, `infeasible`, or `error`).

## Runtime and deployment (high level)

- The service runs as a container.
- Deployments are automated with GitHub Actions.
- The container is deployed to Google Cloud Run.
- Sensitive values (such as API token) are read from Secret Manager.

## Data model today

- Core data is kept in repository CSV files under `data/`.
- This keeps the setup simple and reproducible.
- The current data changes infrequently.
- The ingredient pool (`fasa_core/config/ingredient_pool_africa.csv`) is country-aware:
  each ingredient carries a `countries` tag (ISO-2: KE/NG/ZM). An optional `country` on
  `/formulate` flags which ingredients are *locally available* in the response; it never
  restricts the optimization. The pool is regenerated from source lists by
  `scripts/build_ingredient_pool.py`.
- Two hand-maintained tables hold the min/max inclusion layer:
  `fasa_core/config/nutrient_limits.csv` (bounds on dietary nutrient levels) and
  `fasa_core/config/ingredient_limits.csv` (bounds on single-ingredient inclusion).
  They express what a mill can actually formulate and process, which composition data
  alone does not. Both ship without data rows pending the values; filling the columns
  activates the layer with no code change, and clients can supply bounds per request
  in the meantime.

## Versioning and changes

- Versioning follows Semantic Versioning.
- Release notes are tracked in `CHANGELOG.md`.
- More details are in `docs/versioning.md`.

## Where to start

- Product/integration overview: `README.md`
- API usage and integration notes: `docs/integration.md`
- Version and release rules: `docs/versioning.md`

