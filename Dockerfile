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
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libsundials-dev mpi-default-dev octave && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=frontend /app/frontend/dist frontend/dist
COPY external/torord/cellml/ToRORd_dynCl_endo.cellml external/torord/cellml/ToRORd_dynCl_endo.cellml
COPY external/myokit-models/c/ohara-2011.mmt external/myokit-models/c/ohara-2011.mmt
COPY external/myokit-models/c/grandi-2011.mmt external/myokit-models/c/grandi-2011.mmt
COPY external/myokit-models/c/fabbri-2017.mmt external/myokit-models/c/fabbri-2017.mmt
COPY external/grandits_emulator/cardiomyocyte_emulator external/grandits_emulator/cardiomyocyte_emulator
COPY model_assets model_assets
COPY external/ni_2023_atrial/Single_Cells external/ni_2023_atrial/Single_Cells
COPY ["external/herrera_2025_atrial/Single Cell", "external/herrera_2025_atrial/Single Cell"]
COPY backend/native backend/native
COPY scripts/build_ni_2023.sh scripts/build_ni_2023.sh
COPY scripts/prepare_ni_build_source.py scripts/prepare_ni_build_source.py
RUN CXX=mpic++ SUNDIALS_PREFIX=/usr scripts/build_ni_2023.sh
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
