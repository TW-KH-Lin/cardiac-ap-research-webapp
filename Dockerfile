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
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates curl git libsundials-dev mpi-default-dev && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r backend/requirements.txt
# Debian Trixie's Octave is built without working ode15s/SUNDIALS support.
# Use the same pinned conda-forge Octave release as the validated research
# runtime, and verify its stiff solver during image build.
RUN mkdir -p /app/.runtime/bin \
    && curl -fsSL https://github.com/mamba-org/micromamba-releases/releases/download/2.9.0-0/micromamba-linux-64 -o /app/.runtime/bin/micromamba \
    && echo '366cd9cd8be14df1ab8ed50352a82111082a36686b2d389fdb79a92c3fafb3e3  /app/.runtime/bin/micromamba' | sha256sum -c - \
    && chmod +x /app/.runtime/bin/micromamba \
    && /app/.runtime/bin/micromamba create --yes --root-prefix /app/.runtime/mamba --name octave --channel conda-forge --strict-channel-priority octave=10.3.0 \
    && /app/.runtime/bin/micromamba run --root-prefix /app/.runtime/mamba --name octave octave-cli --quiet --eval "[t,y]=ode15s(@(t,y)-y,[0 1],1); assert(abs(y(end)-exp(-1))<1e-3)" \
    && rm -rf /app/.runtime/mamba/pkgs
# Myokit compiles model-specific C extensions on the first simulation. Its
# default file-descriptor capture conflicts with Uvicorn's threaded request
# logging in container runtimes; keep compiler diagnostics but avoid its
# low-level file-descriptor capture mode.
RUN mkdir -p /root/.config/myokit \
    && printf '[compatibility]\nno_fd_capture = True\n' > /root/.config/myokit/myokit.ini
# Keep first-run Myokit model compilation within the memory available on the
# free web-service instance. The equations and solver tolerances are unchanged.
ENV CC="mpicc" CFLAGS="-O0"
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
