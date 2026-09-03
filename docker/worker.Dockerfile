FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
# Every package listed in [tool.hatch.build.targets.wheel]. Missing one here
# does not fail the build -- it fails at import time inside the running
# container, which is a much worse place to find out.
COPY apps ./apps
COPY backtesting ./backtesting
COPY brain ./brain
COPY config ./config
COPY data ./data
COPY experiments ./experiments
COPY integrations ./integrations
COPY models ./models
COPY observability ./observability
COPY paper_trading ./paper_trading
COPY quant ./quant
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir .

# Not root: a container that never needs to write to its own image
# should not be able to.
RUN useradd --create-home --uid 10001 tradingbrain
USER tradingbrain

CMD ["python", "-m", "apps.worker.main", "loop"]
