FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/ /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.lock && pip install --no-cache-dir --no-deps /app/backend
COPY --from=frontend /build/frontend/dist /app/frontend/dist
RUN useradd --uid 10001 --create-home chronoverse && mkdir /data && chown 10001:10001 /data
USER 10001
ENV CHRONOVERSE_DB=/data/chronoverse.sqlite3 CHRONOVERSE_STATIC_DIR=/app/frontend/dist PYTHONUNBUFFERED=1
EXPOSE 8000 8001
CMD ["uvicorn", "chronoverse.api:app", "--host", "0.0.0.0", "--port", "8000"]
