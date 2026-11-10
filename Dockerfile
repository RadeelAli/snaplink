# ---- build stage ----
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

# ---- runtime stage ----
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 snaplink
WORKDIR /srv
COPY --from=builder /install /usr/local
COPY app ./app
RUN mkdir /data && chown snaplink /data
USER snaplink

ENV SNAPLINK_DB_PATH=/data/snaplink.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
