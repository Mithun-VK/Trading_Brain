FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY apps ./apps
COPY brain ./brain
COPY quant ./quant
COPY data ./data
COPY integrations ./integrations
COPY models ./models
COPY config ./config
COPY scripts ./scripts

RUN pip install --no-cache-dir .

CMD ["python", "-m", "apps.worker.main", "loop"]
