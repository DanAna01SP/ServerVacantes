FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/datos/data \
    UPLOADS_DIR=/datos/uploads

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static ./static

RUN useradd --create-home --uid 1000 web \
    && mkdir -p /datos/data /datos/uploads \
    && chown -R web:web /datos
USER web

EXPOSE 5001
VOLUME ["/datos"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/salud')"

# Un solo proceso con varios hilos: el candado que protege los JSON es por proceso
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--threads", "8", "app:app"]
