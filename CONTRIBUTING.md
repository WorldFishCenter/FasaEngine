## Contributing

### Development setup

Prerequisites:
- Python 3.10+

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run tests

```bash
pytest -q
```

### Run the demo

```bash
python -m examples.tilapia_starter_demo
```

### Run the API locally

```bash
uvicorn fasa_api.main:app --reload --port 8000
```

Then open `http://127.0.0.1:8000/docs`.

### PR checklist

Before opening a pull request:

- [ ] Run tests locally (`pytest -q`).
- [ ] If API behavior changed, update related documentation (`README.md`, `docs/integration.md`, or `docs/architecture.md`).
- [ ] If the change is user-visible, add an entry under `## [Unreleased]` in `CHANGELOG.md`.

Before merge:

- [ ] Ensure CI is green.
- [ ] Confirm version consistency checks pass.

### Release checklist

When preparing a new release:

- [ ] Update version in `pyproject.toml`.
- [ ] Update `__version__` in `fasa_core/__init__.py` to the same value.
- [ ] Add a matching version section in `CHANGELOG.md` using `## [X.Y.Z] - YYYY-MM-DD`.
- [ ] Keep `## [Unreleased]` for future changes after moving completed notes to the new release.
- [ ] Merge to `main` (release workflow creates the GitHub release from changelog).
