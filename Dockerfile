FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY *.py .

# Create default data dir (mount a Railway Volume here for persistence)
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/bot.db

CMD ["python", "main.py"]
