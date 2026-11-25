FROM python:3.14.10-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends redis-server tini && rm -rf /var/lib/apt/lists/*
COPY . /app
RUN python verify_render_environment.py --pre && python -m pip install --no-cache-dir -r requirements.render.txt && python -m pip check && python verify_render_environment.py
RUN useradd --create-home --uid 10001 stageuser && mkdir -p /app/instance /app/static/uploads && chown -R stageuser:stageuser /app/instance /app/static/uploads
USER stageuser
CMD ["/usr/bin/tini","-g","--","/bin/sh","/app/infra/d01-stage-start.sh"]
