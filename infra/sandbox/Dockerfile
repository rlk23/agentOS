FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.4.2 \
    && useradd --uid 1000 --create-home agent
COPY tools.py lifetime.py /opt/agentos/
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
WORKDIR /workspace
USER 1000:1000
ENTRYPOINT ["python", "-I", "/opt/agentos/lifetime.py"]
