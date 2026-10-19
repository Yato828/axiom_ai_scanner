FROM node:22-bookworm-slim AS browser
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-fund
COPY scripts/build-web.mjs scripts/build-web.mjs
COPY web web
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home mixer
COPY --chown=mixer:mixer axiom_scanner axiom_scanner
COPY --chown=mixer:mixer api api
COPY --chown=mixer:mixer axiom_dashboard.py config.example.json ./
COPY --chown=mixer:mixer data data
COPY --from=browser --chown=mixer:mixer /build/web web
RUN mkdir /app/logs && chown mixer:mixer /app/logs
USER mixer
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn axiom_scanner.web_wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 90 --max-requests 2000 --max-requests-jitter 200"]
