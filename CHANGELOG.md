# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Cloud Run deployment workflow for automated deployments.
- API token protection via `Authorization: Bearer` or `X-API-Key`.
- Readiness probe endpoint (`/ready`) and structured request/solver logging.
- Integration, architecture, and versioning documentation under `docs/`.

### Changed
- Expanded API schema modeling and OpenAPI metadata coverage.
- Updated README with Cloud Run setup and API testing instructions.

## [0.1.0] - 2026-05-07

### Added
- Initial MVP release of FASA feed formulation engine.
- FastAPI endpoints: `/health`, `/supported`, `/formulate`, `/validate-recipe`.
- LP optimization core (PuLP + HiGHS), PAFF benchmark checks, and smoke tests.

