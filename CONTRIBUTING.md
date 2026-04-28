## Contributing

### Development setup

Prerequisites:
- Python 3.10+ recommended

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
