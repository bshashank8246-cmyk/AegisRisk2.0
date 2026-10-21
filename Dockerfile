FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# One worker: the model lives in memory, so retraining must hit the same process.
CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT}"]
