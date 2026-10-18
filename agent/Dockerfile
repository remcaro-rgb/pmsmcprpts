FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pms_agent ./pms_agent
EXPOSE 7001
CMD ["python", "-m", "pms_agent", "--host", "0.0.0.0", "--port", "7001"]
