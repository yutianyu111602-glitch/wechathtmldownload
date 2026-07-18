FROM node:20-alpine

RUN apk add --no-cache curl bash

WORKDIR /app
COPY package.json ./
COPY package-lock.json ./
RUN apk add --no-cache --virtual .build-deps python3 make g++ \
    && npm ci --omit=dev \
    && apk del .build-deps
COPY assets ./assets
COPY data ./data
COPY src ./src
COPY scripts ./scripts

RUN chmod +x /app/scripts/weekly_pipeline.sh && mkdir -p /app/logs

ENV NODE_ENV=production
ENV WEEKLY_ACTIVITY_API_DIR=/app/data/current_release
ENV NODE_OPTIONS="--max-old-space-size=1536"
ENV ATLAS_MINIAPP_PRELOAD="1"
ENV PORT=8787
EXPOSE 8787

# ── LLM / DeepSeek 配置（部署时通过 CloudBase 控制台或 deploy 命令覆盖） ──
ENV DEEPSEEK_API_KEY=""
ENV DEEPSEEK_MODEL="deepseek-v4-pro"
ENV DEEPSEEK_TIMEOUT_MS="120000"
ENV DEEPSEEK_THINKING_TYPE="disabled"
ENV DEEPSEEK_ENRICH_ENABLED="true"
ENV DEEPSEEK_ENRICH_CONCURRENCY="3"
ENV LLM_MATERIALIZE_ENABLED="true"
ENV LLM_MATERIALIZE_SUMMARY_ONLY="1"

CMD ["node", "src/server.mjs"]
