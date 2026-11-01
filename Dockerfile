# FactVerify Civic Agent - one container: FastAPI server + built React client + Playwright Chromium + ffmpeg.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install -r server/requirements.txt && python -m playwright install --with-deps chromium

COPY server server
COPY client/dist client/dist

WORKDIR /app/server
# Heavy offline models are off in the cloud; cloud AI keys (set in the host's dashboard) do those jobs.
ENV FACTVERIFY_RUNTIME_DIR=/tmp/factverify LOCAL_AI_IMAGE_DISABLED=true AGENT_HEADLESS=true
EXPOSE 8000
CMD ["sh", "-c", "FACTVERIFY_PUBLIC_BASE_URL=http://127.0.0.1:${PORT:-8000} exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
