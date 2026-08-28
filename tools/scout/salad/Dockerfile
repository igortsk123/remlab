# Образ Hunyuan3D 2.1 (геометрия + PBR) для SaladCloud Container Engine.
#
# СЛЕДУЕТ ОФИЦИАЛЬНОМУ РЕЦЕПТУ Tencent (`docker/Dockerfile` в репозитории 2.1), а не
# собственной выдумке. Первая моя версия была короче и красивее, но не запустилась бы:
# в ней не хватало трёх обязательных шагов, каждый из которых роняет ТОЛЬКО в рантайме,
# то есть уже на платной ноде —
#   1. чекпойнт RealESRGAN (`hy3dpaint/ckpt/RealESRGAN_x4plus.pth`) — апскейл текстур;
#   2. две правки путей в исходниках (`textureGenPipeline.py`, `utils/multiview_utils.py`):
#      апстрим ищет конфиги относительно корня репозитория;
#   3. системные библиотеки для EGL/CGAL/Eigen, без которых не собирается растеризатор.
# Отклонения от официального — только два, оба осознанные: системный python вместо miniconda
# (минус ~3 ГБ, conda здесь ничего не даёт) и multi-stage не применяется, потому что
# `custom_rasterizer` ставится в editable-режиме и в чужую ступень не переносится.
#
# ДВА ТЕГА из одного файла:
#   4090/3090 (Ada/Ampere) → CUDA_TAG=12.4.1 TORCH_SPEC="torch==2.5.1 torchvision==0.20.1"
#                            TORCH_INDEX=cu124  ← комбинация, проверенная апстримом
#   5090 (Blackwell)       → CUDA_TAG=12.8.1 TORCH_SPEC="torch torchvision"
#                            TORCH_INDEX=cu128  ← апстримом НЕ проверена, наш риск
# Один образ на обе архитектуры не годится: собранный под 12.8 не запустится на 4090.
#
# ЛИМИТ ПЛАТФОРМЫ: Salad не скачает образ больше 35 ГБ в сжатом виде. Гейт в build.sh считает
# сжатый размер по реестру (`docker manifest inspect`), а не локальный `docker images`.

ARG CUDA_TAG=12.4.1
FROM nvidia/cuda:${CUDA_TAG}-devel-ubuntu22.04

ARG TORCH_SPEC="torch==2.5.1 torchvision==0.20.1"
ARG TORCH_INDEX=cu124
ARG TORCH_ARCH="8.6;8.9"
ARG HY_COMMIT=main
ARG BAKE_WEIGHTS=1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_RETRIES=10 \
    PIP_DEFAULT_TIMEOUT=90 \
    CUDA_HOME=/usr/local/cuda \
    PYOPENGL_PLATFORM=egl \
    TORCH_CUDA_ARCH_LIST=${TORCH_ARCH} \
    HF_HOME=/opt/hf \
    WEIGHTS_DIR=/opt/weights \
    PIPELINE_VERSION=v1 \
    STORAGE_BACKEND=http \
    STAGED=1 \
    PORT=8000
ENV PATH=${CUDA_HOME}/bin:${PATH} \
    LD_LIBRARY_PATH=${CUDA_HOME}/lib64:/usr/lib64:${LD_LIBRARY_PATH}

# Системные зависимости — список апстрима. Урезать нельзя: libcgal/libeigen нужны
# растеризатору при компиляции, libegl/libgles — рендереру в рантайме.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git wget cmake pkg-config ninja-build \
      python3.10 python3-pip python3-dev python3-setuptools \
      libeigen3-dev libcgal-dev \
      libglvnd0 libglvnd-dev libgl1 libglx0 libegl1 libgles2 \
      libgl1-mesa-dev libegl1-mesa-dev libgles2-mesa-dev \
      libglib2.0-0 libxrender1 libsm6 libxext6 libxi6 libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3.10 /usr/bin/python

RUN pip install --upgrade pip && \
    pip install ${TORCH_SPEC} --index-url https://download.pytorch.org/whl/${TORCH_INDEX}

# Коммит пинуется: результат генерации обязан быть воспроизводим, и манифест каждого ассета
# ссылается именно на этот commit.
RUN git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git /opt/hunyuan && \
    cd /opt/hunyuan && git checkout ${HY_COMMIT} && \
    git rev-parse HEAD > /opt/hunyuan/.pinned_commit && rm -rf /opt/hunyuan/.git

# Зависимости ставим ДВУМЯ слоями, а не одним: пакетов под сотню, и обрыв закачки на
# последнем (ловили 28.08: «Response ended prematurely» на safetensors) заставлял бы
# переставлять всё заново. Разделение делает повтор дешёвым.
# Blender (`bpy==4.0`) из requirements апстрима убираем ДО установки: этой версии на PyPI
# больше нет, колёс под python3.10 не осталось ни у одной (проверено 28.08), и официальная
# сборка Tencent сегодня падает здесь же. На нашем пути bpy нужен ровно для OBJ→GLB —
# заменяется чистым trimesh+pygltflib из этого же репозитория. Детали — patch_bpy.py.
COPY patch_bpy.py /tmp/patch_bpy.py
RUN python /tmp/patch_bpy.py && rm -f /tmp/patch_bpy.py

RUN pip install -r /opt/hunyuan/requirements.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm -f /tmp/requirements.txt

# Кастомный растеризатор: editable-режим и -allow-unsupported-compiler — как у апстрима.
# Без флага nvcc отказывается работать со свежим gcc из ubuntu22.04.
RUN cd /opt/hunyuan/hy3dpaint/custom_rasterizer && \
    CUDA_NVCC_FLAGS="-allow-unsupported-compiler" pip install -e .
RUN cd /opt/hunyuan/hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh

# RealESRGAN — апскейл текстур в PBR-стадии. Пропустить нельзя: пайштейн падает при загрузке.
RUN mkdir -p /opt/hunyuan/hy3dpaint/ckpt && \
    wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth \
      -P /opt/hunyuan/hy3dpaint/ckpt

# Правки путей — дословно из официального Dockerfile. Апстрим пишет пути относительно корня
# репозитория, а мы запускаемся не из него.
RUN cd /opt/hunyuan/hy3dpaint && \
    sed -i 's/self\.multiview_cfg_path = "cfgs\/hunyuan-paint-pbr\.yaml"/self.multiview_cfg_path = "hy3dpaint\/cfgs\/hunyuan-paint-pbr.yaml"/' textureGenPipeline.py && \
    cd utils && \
    sed -i 's/custom_pipeline = config\.custom_pipeline/custom_pipeline = os.path.join(os.path.dirname(__file__),"..","hunyuanpaintpbr")/' multiview_utils.py

# Веса — ОТДЕЛЬНЫМ слоем и НИЖЕ кода: правка воркера меняет только верхний тонкий слой,
# и ноды не перекачивают гигабайты заново.
# BiRefNet — локальная вырезка фона. Раньше её делал fal; fal из конвейера убран.
RUN if [ "$BAKE_WEIGHTS" = "1" ]; then \
      python -c "\
from huggingface_hub import snapshot_download as d; \
d('tencent/Hunyuan3D-2.1', local_dir='/opt/weights/hunyuan3d-2.1'); \
d('ZhengPeng7/BiRefNet', local_dir='/opt/weights/birefnet')" && rm -rf /opt/hf; \
    else \
      mkdir -p /opt/weights && echo lazy > /opt/weights/.lazy; \
    fi

# WORKDIR — корень репозитория: относительные пути в конфигах апстрима считаются от него.
WORKDIR /opt/hunyuan
ENV PYTHONPATH=/opt/hunyuan:/opt/hunyuan/hy3dshape:/opt/hunyuan/hy3dpaint:/app
COPY manifest.py preprocess.py pipeline.py storage.py worker.py fetch_weights.py /app/
EXPOSE 8000

# Прогрев (загрузка весов, компиляция ядер) занимает минуты, поэтому start-period щедрый:
# иначе платформа сочтёт живую ноду мёртвой и снимет её с раздачи заданий.
HEALTHCHECK --interval=30s --timeout=10s --start-period=900s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5)"

CMD ["python", "-u", "/app/worker.py"]
