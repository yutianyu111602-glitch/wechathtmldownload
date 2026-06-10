# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY tools/stage7_rewrite/docker/openclaw-weekly/profile_report_entrypoint.py /opt/openclaw/profile_report_entrypoint.py

ENTRYPOINT ["python", "/opt/openclaw/profile_report_entrypoint.py"]
