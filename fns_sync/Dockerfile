FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fns_sync ./fns_sync
# db/init/06_fns.sql is mounted at /app/schema.sql (see docker-compose.yml).
CMD ["python", "-m", "fns_sync", "daemon"]
