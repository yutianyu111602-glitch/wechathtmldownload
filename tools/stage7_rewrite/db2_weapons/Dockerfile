# syntax=docker/dockerfile:1
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    requests beautifulsoup4 mutagen

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY weapons/ /opt/db2-weapons/weapons/
COPY entrypoint.py /opt/db2-weapons/

ENTRYPOINT ["python3", "/opt/db2-weapons/entrypoint.py"]
