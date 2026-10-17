FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pms_mcp ./pms_mcp
EXPOSE 8000
CMD ["python", "-m", "pms_mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
