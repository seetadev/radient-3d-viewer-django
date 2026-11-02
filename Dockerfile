# syntax=docker/dockerfile:1

# --- stage 1: minify the browser JS (sources in git stay readable) -------------------------
FROM node:22-alpine AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY tools/minify.mjs tools/minify.mjs
COPY app/static app/static
RUN node tools/minify.mjs app/static

# --- stage 2: runtime -------------------------------------------------------------------------
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY manage.py ./
COPY Radient_Django Radient_Django
COPY app app
COPY --from=assets /build/app/static app/static
# The key is only needed to import settings; the real one comes from the environment at run time.
RUN DJANGO_SECRET_KEY=build-time-only python manage.py collectstatic --noinput

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin radient
USER 10001
EXPOSE 8000
# ALLOWED_HOSTS is still ['localhost'] (made configurable in the security PR), so send that Host header.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:%s/' % os.environ.get('PORT','8000'), headers={'Host':'localhost'}), timeout=2)"
CMD ["sh", "-c", "exec gunicorn Radient_Django.wsgi --bind 0.0.0.0:${PORT} --workers 2 --worker-tmp-dir /dev/shm --no-control-socket --access-logfile -"]
