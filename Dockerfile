FROM python:3.13-slim
ARG GIT_COMMIT=unknown
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY maintenance ./maintenance
COPY tests ./tests
COPY Dockerfile docker-compose.yml ./
COPY install-update-helper.sh ./
RUN python -m compileall -q app maintenance tests
RUN mkdir -p /data /maintenance
ENV FLOW_DB_PATH=/data/flow.db
ENV FLOW_GIT_COMMIT=${GIT_COMMIT}
EXPOSE 8010
HEALTHCHECK --interval=10s --timeout=4s --start-period=15s --retries=6 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/health', timeout=3).read()" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
