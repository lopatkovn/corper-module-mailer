FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install corper-shared (see fn docstring for the two paths).
ARG CORPER_SHARED_URL=http://10.101.10.181:5000/api/deploy/shared/corper-shared.tar.gz
COPY _corper-shared /tmp/cs/
RUN if [ -f /tmp/cs/pyproject.toml ]; then \
        pip install --no-cache-dir /tmp/cs; \
    else \
        echo ">>> No bundled corper-shared (dev build) — downloading from ${CORPER_SHARED_URL}"; \
        curl -fsSL "${CORPER_SHARED_URL}" -o /tmp/cs.tar.gz \
        && rm -rf /tmp/cs && mkdir -p /tmp/cs && tar -xzf /tmp/cs.tar.gz -C /tmp/cs \
        && pip install --no-cache-dir /tmp/cs/corper-shared \
        && rm -f /tmp/cs.tar.gz; \
    fi && rm -rf /tmp/cs

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
