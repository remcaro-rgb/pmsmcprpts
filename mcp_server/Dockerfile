FROM python:3.13-slim
# Fonts for chart text (SVG -> PNG rendering).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pms_mcp ./pms_mcp
EXPOSE 7000
CMD ["python", "-m", "pms_mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "7000"]
