FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for geospatial packages (e.g. GEOS, PROJ, GDAL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgeos-dev \
    libproj-dev \
    gdal-bin \
    libgdal-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source and ML models
COPY backend /app/backend

WORKDIR /app/backend

# Set Python path to ensure module imports resolve smoothly
ENV PYTHONPATH=/app/backend
ENV PORT=8000
ENV GEE_MOCK_FALLBACK=false
ENV ALLOW_SYNTHETIC_DATA=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
