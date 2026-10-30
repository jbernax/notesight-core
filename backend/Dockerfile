FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required for OpenCV, CairoSVG, and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged user appuser (UID 10001) for defense-in-depth container isolation
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/sh -d /app appuser

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install standalone open-source OMR engine (AGPL-3.0-or-later, invoked across subprocess boundary)
COPY packages/notesight-omr-engine /opt/notesight-omr-engine
RUN pip install --no-cache-dir /opt/notesight-omr-engine

# Pre-download OMR neural network checkpoints during image build
RUN notesight-omr --init || true

COPY backend/ .
RUN mkdir -p /app/storage/uploads /app/storage/results && \
    chown -R appuser:appgroup /app

USER appuser

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

