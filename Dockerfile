FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PORT=8080

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY fasa_core ./fasa_core
COPY fasa_api ./fasa_api
COPY data ./data
COPY README.md ./README.md
COPY pyproject.toml ./pyproject.toml

EXPOSE 8080

CMD ["sh", "-c", "uvicorn fasa_api.main:app --host 0.0.0.0 --port ${PORT}"]
