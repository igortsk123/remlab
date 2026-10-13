# Сервис кадров демо `remlab-draft` (план b2b-08, ADR-0267): образ ИЗ РЕПОЗИТОРИЯ вместо собранного руками
# в августе и докладываемого `docker cp`. Состав — ровно то, что импортирует HTTP-рендер: сервис, рендер, меши,
# планировщик (`services/planner-solver/planner` + его `rules/`) и четыре правила scout. Зависимости — с
# версиями, снятыми с работающего контейнера 13.10. Сборка: контекст — корень репозитория, список файлов —
# `infra/draft/Dockerfile.dockerignore` (без него в контекст уехали бы гигабайты tools/).
FROM python:3.12-slim
ARG DRAFT_VERSION=dev
ENV PYTHONUNBUFFERED=1 DRAFT_VERSION=${DRAFT_VERSION}
RUN pip install --no-cache-dir numpy==2.5.2 scipy==1.18.1 trimesh==4.5.3 shapely==2.1.2 pillow==12.3.0 \
      pydantic==2.13.4 fast_simplification==0.2.0
WORKDIR /app
COPY services/planner-solver/planner/ /app/planner/
COPY services/planner-solver/rules/ /app/rules/
COPY tools/scout/rules/asset-strategies.json tools/scout/rules/capabilities.json \
     tools/scout/rules/openai_prices.json tools/scout/rules/practice_priors.json /app/rules/
COPY tools/scout/draft_service.py tools/scout/draft_guard.py tools/scout/draft_render.py \
     tools/scout/asset_strategy.py tools/scout/falmini.py tools/scout/improve_mode.py \
     tools/scout/mesh_render.py tools/scout/scene_mesh.py tools/scout/styles.json /app/
# сборка падает, если HTTP-рендеру чего-то не хватает (а не ночью на первом кадре)
RUN python -c "import draft_service, draft_render, mesh_render, scene_mesh, improve_mode, asset_strategy; print('imports ok')"
EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8099/health',timeout=3)"
CMD ["python", "draft_service.py"]
