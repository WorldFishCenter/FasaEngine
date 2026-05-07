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
- `fasa_core/`: core logic (data loading, constraints, optimization, validation)
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

## Versioning and changes

- Versioning follows Semantic Versioning.
- Release notes are tracked in `CHANGELOG.md`.
- More details are in `docs/versioning.md`.

## Where to start if you are new

- Product/integration overview: `README.md`
- API usage and integration notes: `docs/integration.md`
- Version and release rules: `docs/versioning.md`

