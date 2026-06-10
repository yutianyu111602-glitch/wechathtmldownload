# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY db2_external_link_entrypoint.py /opt/openclaw/db2_external_link_entrypoint.py

ENTRYPOINT ["python", "/opt/openclaw/db2_external_link_entrypoint.py"]
