# ── FORGE — multi-stage image for Alibaba Cloud ACR -> ECS ───────────────────
# Stage 1: build the React field console.
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend that serves the API/WebSocket and the built console.
FROM python:3.12-slim AS backend
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /frontend/dist ./frontend_dist
ENV FORGE_FRONTEND_DIST=/app/frontend_dist

# Long-lived WebSocket sessions: a single worker (sticky realtime session per conn),
# generous timeouts, WS protocol enabled.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--ws", "websockets", \
     "--timeout-keep-alive", "75", "--proxy-headers"]
