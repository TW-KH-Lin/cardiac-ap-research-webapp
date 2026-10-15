FROM node:24-alpine AS frontend
WORKDIR /app/frontend
RUN npm install -g pnpm@11.19.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN CI=true pnpm install --frozen-lockfile --config.dangerouslyAllowAllBuilds=true
COPY backend/app/models/manifest.json /app/backend/app/models/manifest.json
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates curl git libsundials-dev mpi-default-dev octave && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r backend/requirements.txt
# Myokit compiles model-specific C extensions on the first simulation. Its
# default file-descriptor capture conflicts with Uvicorn's threaded request
# logging in container runtimes; keep compiler diagnostics but avoid its
# low-level file-descriptor capture mode.
RUN mkdir -p /root/.config/myokit \
    && printf '[compatibility]\nno_fd_capture = True\n' > /root/.config/myokit/myokit.ini
# Keep first-run Myokit model compilation within the memory available on the
# free web-service instance. The equations and solver tolerances are unchanged.
ENV CFLAGS="-O0"
COPY backend/app backend/app
COPY --from=frontend /app/frontend/dist frontend/dist
COPY backend/native backend/native
COPY scripts scripts
# Fetch fixed upstream revisions and compile the Ni adapter while the image is
# built. The running service performs no model downloads.
RUN CXX=mpic++ SUNDIALS_PREFIX=/usr bash scripts/fetch_models.sh \
    && find external -type d -name .git -prune -exec rm -rf '{}' + \
    && rm -rf .build
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]
