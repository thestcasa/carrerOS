FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY candidates ./candidates
RUN pip install --no-cache-dir .
RUN playwright install --with-deps chromium

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.api:app --host 0.0.0.0 --port 8000"]
