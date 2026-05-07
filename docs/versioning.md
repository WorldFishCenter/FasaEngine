# Versioning and Release Policy

This project uses Semantic Versioning (`MAJOR.MINOR.PATCH`) and a repository-level changelog.

## Source of truth

- Package version: `pyproject.toml` (`[project].version`)
- Runtime API version exposure: `fasa_core/__init__.py` (`__version__`)
- Human-readable release notes: `CHANGELOG.md`

These three must be updated together for each release.

## SemVer rules used in this repository

- **PATCH** (`x.y.Z`): bug fixes, performance improvements, docs-only updates, and non-breaking internal changes.
- **MINOR** (`x.Y.z`): backward-compatible feature additions (new optional fields, new endpoints, new non-breaking behavior).
- **MAJOR** (`X.y.z`): breaking changes (removed/renamed endpoint fields, removed routes, changed required request shape, incompatible behavior changes).

## API compatibility expectations

- OpenAPI (`/openapi.json`) is the integration contract.
- Breaking contract changes require:
  1) a MAJOR version bump, and
  2) a clear changelog entry with migration notes.

## Release process

1. Finalize pending items in `CHANGELOG.md` under `## [Unreleased]`.
2. Decide next SemVer version.
3. Update:
   - `pyproject.toml` version
   - `fasa_core/__init__.py` `__version__`
   - `CHANGELOG.md` (`[Unreleased]` -> new dated version section)
4. Run tests (`pytest -q`) and CI checks.
5. Merge to `main`: `.github/workflows/release.yml` automatically creates tag/release from `pyproject.toml` + `CHANGELOG.md`.
6. If no release is created, check workflow logs for version/changelog mismatch.

## Changelog conventions

- Keep entries concise and grouped under:
  - `Added`
  - `Changed`
  - `Deprecated`
  - `Removed`
  - `Fixed`
  - `Security`
- Add migration notes whenever a consumer action is required.

