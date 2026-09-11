FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/streamlit-ui
COPY streamlit-ui/requirements.txt /app/streamlit-ui/requirements.txt
RUN pip install --no-cache-dir -r streamlit-ui/requirements.txt
COPY shared /app/shared
COPY .streamlit/config.toml /app/.streamlit/config.toml
COPY streamlit-ui /app/streamlit-ui
USER 10001:10001
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "streamlit-ui/app.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true", "--browser.gatherUsageStats", "false"]
