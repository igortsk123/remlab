# Образ Hunyuan3D 2.1 (геометрия + PBR) для SaladCloud Container Engine.
#
# Собирается в два тега из одного файла — CUDA задаётся аргументом:
#   4090 (Ada, sm_89)      → CUDA_TAG=12.1.1  TORCH_INDEX=cu121  TORCH_ARCH=8.9
#   5090 (Blackwell, sm_120) → CUDA_TAG=12.8.1 TORCH_INDEX=cu128  TORCH_ARCH=12.0
# Один образ на обе карты не годится: собранный под CUDA 12.8 не запустится на 4090.
#
# ЛИМИТ ПЛАТФОРМЫ: Salad не скачает образ больше 35 ГБ в сжатом виде. Целимся в ≤28 ГБ,
# размер проверяется гейтом в build.sh по remote compressed (`docker manifest inspect`),
# а не по локальному `docker images` — они расходятся в разы.
#
# ПОРЯДОК СЛОЁВ ВАЖЕН: веса (~15 ГБ) кладутся ОДНИМ слоем ниже кода. Правка воркера тогда
# меняет только верхний тонкий слой, и ноды не перекачивают веса заново.

ARG CUDA_TAG=12.1.1
FROM nvidia/cuda:${CUDA_TAG}-cudnn8-devel-ubuntu22.04 AS base

ARG TORCH_INDEX=cu121
ARG TORCH_ARCH=8.9
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    TORCH_CUDA_ARCH_LIST=${TORCH_ARCH} \
    WEIGHTS_DIR=/opt/weights

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3-pip git build-essential ninja-build \
      libgl1 libglib2.0-0 libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3.10 /usr/bin/python

# --- слой 1: torch (тяжёлый, меняется реже всего) ---
RUN pip install --upgrade pip && \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/${TORCH_INDEX}

# --- слой 2: исходники Hunyuan3D 2.1 + компиляция расширений ---
# Коммит пинуется: результат генерации обязан быть воспроизводим, а manifest ассета
# ссылается именно на этот commit.
ARG HY_COMMIT=main
RUN git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git /opt/hunyuan && \
    cd /opt/hunyuan && git checkout ${HY_COMMIT} && \
    echo "${HY_COMMIT}" > /opt/hunyuan/.pinned_commit

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && \
    pip install -r /opt/hunyuan/requirements.txt

# Кастомный растеризатор и дифференцируемый рендерер собираются из исходников —
# без них PBR-стадия не запускается.
RUN cd /opt/hunyuan/hy3dpaint/custom_rasterizer && pip install -e . && \
    cd /opt/hunyuan/hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh

# --- слой 3: веса, ОДНИМ слоем (~15 ГБ) ---
# Тянуть их с HuggingFace на старте ноды нельзя: у бытовых нод узкий канал, и это добавляет
# минуты к каждому холодному запуску, причём уже в тарифицируемом состоянии `running`.
# BiRefNet — локальная вырезка фона. Раньше вырезку делал fal; fal из конвейера убран,
# поэтому модель едет внутри образа.
RUN python -c "\
from huggingface_hub import snapshot_download as d; \
d('tencent/Hunyuan3D-2.1', local_dir='/opt/weights/hunyuan3d-2.1', \
  allow_patterns=['hunyuan3d-dit-v2-1/*','hunyuan3d-paintpbr-v2-1/*']); \
d('ZhengPeng7/BiRefNet', local_dir='/opt/weights/birefnet')" && \
    rm -rf /opt/hf

# --- слой 4: наш код (тонкий, меняется часто) ---
WORKDIR /app
COPY manifest.py preprocess.py pipeline.py storage.py worker.py /app/

ENV PYTHONPATH=/opt/hunyuan:/app \
    PIPELINE_VERSION=v1 \
    PORT=8000
EXPOSE 8000

# Job Queue опрашивает /health и снимает ноду с раздачи, если она перестала отвечать.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5)"

CMD ["python", "-u", "worker.py"]
