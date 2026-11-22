#!/bin/bash
# Следит за папкой прогонов StableGen и для каждого нового painted.glb рисует кадры 0°/45° (sg_frames.sh) в <папка кадров>/<имя прогона>.
#   sg_frames_watch.sh <папка прогонов> <папка кадров> [пауза_с]
# Работает, пока не убьют; готовое не повторяет (признак — 04_az045_clay.png). Печатает строку на каждый готовый набор.
set -u
RUNS=$1
FR=$2
PAUSE=${3:-20}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$FR"
while true; do
  for g in "$RUNS"/*/blender/painted.glb; do
    [ -f "$g" ] || continue
    [ -n "${REF:-}" ] && [ ! "$g" -nt "$REF" ] && continue      # REF=<файл-метка>: брать только результаты новее метки (старые кадры уже сделаны)
    name=$(basename "$(dirname "$(dirname "$g")")")
    out="$FR/$name"
    [ -f "$out/04_az045_clay.png" ] && continue
    echo "$(date -u +%T) кадры: $name"
    "$HERE/sg_frames.sh" "$g" "$out" > "$FR/$name.log" 2>&1
    echo "$(date -u +%T) готово: $out ($(ls "$out" 2>/dev/null | grep -c png) png)"
  done
  sleep "$PAUSE"
done
