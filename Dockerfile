FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py bot.py downloader.py stats.py ./
COPY templates/ templates/

RUN printf '#!/bin/sh\ncd /app && exec python stats.py "$@"\n' > /usr/local/bin/mp3-stats \
    && chmod +x /usr/local/bin/mp3-stats

EXPOSE 5050

CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "2", "--timeout", "300", "app:app"]
