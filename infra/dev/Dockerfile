# DEV-конвейер remlab в контейнере (план b2b-08 п.1, ADR-0284): каталог, обогащение, стиль, меши (заказ на Salad),
# сборка и публикация демо, ночной экзамен — то, что сейчас живёт на домашнем компьютере. Пути внутри повторяют
# домашние (`/home/pakar/...`): старые скрипты держат их в коде. База — отдельный контейнер `remlab-devdb`, к нему
# скрипты ходят `docker exec` — поэтому внутри docker CLI и сокет хоста. Секреты — один `.env` рядом с compose.
FROM python:3.14-slim
ARG SUPERCRONIC=v0.2.33
ARG TARGETARCH=amd64
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git openssh-client rsync procps jq nodejs npm docker-cli \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /usr/local/bin/supercronic \
       https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC}/supercronic-linux-${TARGETARCH} \
    && chmod +x /usr/local/bin/supercronic
RUN useradd -m -u 1000 -s /bin/bash pakar
USER pakar
ENV HOME=/home/pakar PYTHONUNBUFFERED=1
COPY --chown=pakar infra/dev/requirements.txt /tmp/requirements.txt
RUN python -m venv /home/pakar/venvs/scout \
    && /home/pakar/venvs/scout/bin/pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
       -r /tmp/requirements.txt
WORKDIR /home/pakar/igor/remlab
# здоровье: ночной прогон отработал за последние 30 часов (метка `.last-refresh` пишется в самом конце)
HEALTHCHECK --interval=10m --timeout=10s --start-period=2h \
  CMD bash -c 'f=tools/scout/.last-refresh; [ -f "$f" ] && [ $(( $(date +%s) - $(stat -c %Y "$f") )) -lt 108000 ]'
CMD ["supercronic", "-passthrough-logs", "/home/pakar/igor/remlab/infra/dev/crontab"]
