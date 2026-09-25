FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# psycopg (3.x) needs libpq at runtime; build-essential for any binary wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
ARG FOBOS_INSTALL_DEV=false
RUN if [ "$FOBOS_INSTALL_DEV" = "true" ]; then \
      pip install --default-timeout=120 --no-cache-dir -r requirements/dev.txt; \
    else \
      pip install --default-timeout=120 --no-cache-dir -r requirements/base.txt; \
    fi

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate && python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 60"]
