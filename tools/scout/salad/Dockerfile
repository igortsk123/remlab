# Образ Hunyuan3D 2.1 (геометрия + PBR) для SaladCloud Container Engine.
#
# ДВЕ СТУПЕНИ. Компиляция кастомного растеризатора и дифференцируемого рендерера требует nvcc,
# то есть образа `devel` (~6 ГБ лишнего). В финальный образ он не нужен — туда едет `runtime`
# плюс собранные .so. Это и укладывает нас в лимит платформы, и позволяет собрать образ на
# машине без видеокарты: nvcc компилирует под архитектуру из TORCH_CUDA_ARCH_LIST, живая карта
# при сборке не нужна.
#
# ДВА ТЕГА из одного файла — CUDA задаётся аргументом:
#   4090 (Ada, sm_89)        → CUDA_TAG=12.1.1  TORCH_INDEX=cu121  TORCH_ARCH=8.9
#   5090 (Blackwell, sm_120) → CUDA_TAG=12.8.1  TORCH_INDEX=cu128  TORCH_ARCH=12.0
# Один образ на обе карты не годится: собранный под 12.8 не запустится на 4090.
#
# ВЕСА — переключателем BAKE_WEIGHTS:
#   1 (умолчание) — веса внутри образа. Холодный старт ноды быстрый, но образ тяжелее и
#     сборке нужно больше диска.
#   0 — веса тянутся с HuggingFace при первом старте в /opt/weights (том переживает рестарт
#     контейнера, но не смену ноды). Образ лёгкий и собирается где угодно; плата — 11–13 ГБ
#     докачки на каждой свежей ноде, причём уже в тарифицируемом состоянии `running`.
# Что дешевле — вопрос замера, а не вкуса: пилот меряет обе схемы.
#
# ЛИМИТ ПЛАТФОРМЫ: Salad не скачает образ больше 35 ГБ в сжатом виде. Гейт в build.sh считает
# именно сжатый размер по реестру (`docker manifest inspect`), а не локальный `docker images` —
# они расходятся в разы.

ARG CUDA_TAG=12.1.1

# ============================ ступень 1: сборка расширений ============================
FROM nvidia/cuda:${CUDA_TAG}-cudnn8-devel-ubuntu22.04 AS builder

ARG TORCH_INDEX=cu121
ARG TORCH_ARCH=8.9
ARG HY_COMMIT=main
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 \
    TORCH_CUDA_ARCH_LIST=${TORCH_ARCH}

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3-pip python3.10-dev git build-essential ninja-build \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3.10 /usr/bin/python

RUN pip install --upgrade pip && \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/${TORCH_INDEX}

# Коммит пинуется: результат генерации обязан быть воспроизводим, и манифест каждого ассета
# ссылается именно на этот commit.
RUN git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git /opt/hunyuan && \
    cd /opt/hunyuan && git checkout ${HY_COMMIT} && \
    git rev-parse HEAD > /opt/hunyuan/.pinned_commit && \
    rm -rf /opt/hunyuan/.git

# Колёса кастомных расширений собираем здесь, в финальный образ поедут только они
RUN cd /opt/hunyuan/hy3dpaint/custom_rasterizer && \
      python setup.py bdist_wheel -d /wheels && \
    cd /opt/hunyuan/hy3dpaint/DifferentiableRenderer && \
      bash compile_mesh_painter.sh && \
      mkdir -p /built && cp -a *.so /built/ 2>/dev/null || true

# ============================ ступень 2: финальный образ =============================
FROM nvidia/cuda:${CUDA_TAG}-cudnn8-runtime-ubuntu22.04

ARG TORCH_INDEX=cu121
ARG BAKE_WEIGHTS=1
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    WEIGHTS_DIR=/opt/weights \
    PYTHONPATH=/opt/hunyuan:/app \
    PIPELINE_VERSION=v1 \
    STORAGE_BACKEND=http \
    STAGED=1 \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3-pip libgl1 libglib2.0-0 libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3.10 /usr/bin/python

RUN pip install --upgrade pip && \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/${TORCH_INDEX}

COPY --from=builder /opt/hunyuan /opt/hunyuan
COPY --from=builder /wheels /tmp/wheels
COPY --from=builder /built/ /opt/hunyuan/hy3dpaint/DifferentiableRenderer/

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && \
    pip install -r /opt/hunyuan/requirements.txt && \
    pip install /tmp/wheels/*.whl && \
    rm -rf /tmp/wheels /tmp/requirements.txt

# Веса — ОТДЕЛЬНЫМ слоем и НИЖЕ кода: правка воркера тогда меняет только верхний тонкий слой,
# и ноды не перекачивают гигабайты заново.
# BiRefNet — локальная вырезка фона. Раньше вырезку делал fal; fal из конвейера убран.
RUN if [ "$BAKE_WEIGHTS" = "1" ]; then \
      python -c "\
from huggingface_hub import snapshot_download as d; \
d('tencent/Hunyuan3D-2.1', local_dir='/opt/weights/hunyuan3d-2.1', \
  allow_patterns=['hunyuan3d-dit-v2-1/*','hunyuan3d-paintpbr-v2-1/*']); \
d('ZhengPeng7/BiRefNet', local_dir='/opt/weights/birefnet')" && \
      rm -rf /opt/hf; \
    else \
      mkdir -p /opt/weights && echo "веса тянутся при старте (BAKE_WEIGHTS=0)" > /opt/weights/.lazy; \
    fi

WORKDIR /app
COPY manifest.py preprocess.py pipeline.py storage.py worker.py fetch_weights.py /app/
EXPOSE 8000

# Прогрев может занимать минуты (загрузка весов, компиляция ядер), поэтому start-period
# щедрый: иначе платформа сочтёт живую ноду мёртвой и снимет её с раздачи заданий.
HEALTHCHECK --interval=30s --timeout=10s --start-period=900s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5)"

CMD ["python", "-u", "worker.py"]
