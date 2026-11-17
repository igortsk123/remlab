#!/usr/bin/env bash
# Проба передачи ткани (T-20261117-06/1; владелец TG 1341/1343, план `render-materials-01`, Codex 17.11 `material-realism-answer.md`).
# Одинаковый ракурс и свет F2 (как final2.sh) для всех вариантов; отдельные PNG 1536×1116, 64 сэмпла. Товар не меняется: цвет и форма те же.
#   probe_soft.sh <папка dump гостиной> <папка-вывода>
#  p1  как сейчас (runtime-меш)                                                           — это `final2` (гостиная)
#  p2  оригинал (диван, столик, торшер) вместо runtime-копии, всё как в файле
#  p3  p2 + ткань дивана: шероховатость 0,85, sheen 0,22 / 0,75 (маска: ниже 12 см — ножки без ворса)
#  p4  p3 + плетение: CC0 Fabric036 (рогожка) normal, период ≈ 0,23 см (повтор 60 см), сила 0,35
# Столик (дерево) и торшер (металл) идут в p2 оригиналом — сравнивать с p1 кропами.
DUMP="$1"; O="$2"
S=living-scandi; DGN=living
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
H="$HOME/scout-scenes"
orig() { ls "$H"/mesh3d-cache/"$1".glb 2>/dev/null || ls "$H"/meshes-hunyuan/meshes/hunyuan21/v2/"$1"/*/model.glb | head -1; }
SOFA=$(orig 112923_1000339805231639017)
ROLE_IDS=$(python3 - "$DUMP/scene-export.json" <<'PY'
import json, sys
E = json.load(open(sys.argv[1], encoding="utf-8"))
for m in E["meshes"]:
    if m["role"] in ("столик", "торшер"):
        print(m["role"], m["meshId"])
PY
)
ORIGS=(--orig "диван:$SOFA")
while read -r role id; do [ -n "$id" ] && ORIGS+=(--orig "$role:$(orig "$id")"); done <<< "$ROLE_IDS"
FAB="$HOME/remlab-logs/t66-1117/fabric/Fabric036/Fabric036_1K-JPG_NormalGL.jpg"
F=(--eye 3.9,-0.3 --aim 0.5,-2.4 --lens 26 --cam-h 1.35 --shift-y -0.05 --view 2 --exposure -0.3 --sun-angle 4 --fill 40 --lamp-k 3000 --chandelier 20 --lamps 6 --sheer 0.3 --normal-k 3.5)
mkdir -p "$O"
go() { local tag="$1"; shift; TAG="-$tag" DG="$DGN" EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" C1 64 75 "$O" "${F[@]}" "$@"; }
go p2-original "${ORIGS[@]}"
go p3-sheen "${ORIGS[@]}" --soft-rough 0.85 --sheen 0.22 --sheen-rough 0.75
go p4-weave "${ORIGS[@]}" --soft-rough 0.85 --sheen 0.22 --sheen-rough 0.75 --fabric "$FAB" --fabric-k 0.35 --fabric-tile 60
echo ALLDONE > "$O/done-probe.txt"
