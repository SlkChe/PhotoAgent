FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/core-api
COPY core-api/requirements.txt /app/core-api/requirements.txt
RUN pip install --no-cache-dir -r core-api/requirements.txt
COPY shared /app/shared
COPY core-api/photo_api /app/core-api/photo_api
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "photo_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
