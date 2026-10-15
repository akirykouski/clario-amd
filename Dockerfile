# Clario app image: FastAPI backend + built React SPA. One image, two modes (CLARIO_MODE=patient|clinic).
#   docker build -t clario-app .
#   docker run -p 8800:8800 -e CLARIO_MODE=clinic -e CLARIO_OFFLINE=1 clario-app
# No model weights and no keys in the image: the LLM is reached over LLM_BASE_URL at runtime.

# ---- stage 1: frontend
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: backend + dist
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY train/prompt.py /app/train/prompt.py
COPY --from=web /web/dist /app/frontend/dist

RUN useradd --create-home --uid 10001 clario && mkdir -p /data && chown clario /data
USER clario
ENV PATH="/opt/venv/bin:$PATH" \
    FRONTEND_DIST=/app/frontend/dist \
    CLARIO_HOST=0.0.0.0 \
    CLARIO_PORT=8800 \
    CLARIO_DATA_DIR=/data
VOLUME /data
EXPOSE 8800
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
  CMD python -c "import os,urllib.request as u;u.urlopen('http://127.0.0.1:%s/api/health'%os.environ.get('CLARIO_PORT','8800'),timeout=4)" || exit 1
CMD ["python", "-m", "clario.app"]
