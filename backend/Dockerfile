# Build from the repository root so policies/, prompts/ and data/ are available:
#   docker build -f backend/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

# curl is used by the container health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml .
COPY backend/app ./app
RUN pip install --no-cache-dir -e .

# Policy clauses, versioned prompts and the demo dataset live outside the Python package
COPY policies ./policies
COPY prompts ./prompts
COPY data/sample_attendance.json data/demo_attendance.json ./data/

ENV POLICIES_DIR=/app/policies \
    PROMPTS_DIR=/app/prompts \
    SEED_FILE=/app/data/demo_attendance.json

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
