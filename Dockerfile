FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /app/data
ENV DB_PATH=/app/data/mcp.db PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
