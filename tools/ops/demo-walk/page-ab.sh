#!/usr/bin/env bash
# ЗАМЕР «ДО/ПОСЛЕ» СТРАНИЦЫ ДЕМО (T-20261112-90): две папки сборки (A — до, B — после) через `stage-proxy.mjs`, по N прогонов
# поочерёдно A,B,A,B… (фон машины делится поровну), телефон 375×667, медленный 4G, процессор ×4, холодный кэш, без 3D.
# Итог — `summary.md` в папке отчёта: медиана и p75 по HTML, DCL, данным, первому экрану (ui), LCP, долгим задачам, КБ до экрана.
#   bash tools/ops/demo-walk/page-ab.sh <папка A> <папка B> <папка отчёта> [N=5] [адрес-хвост=?quiz=0&lang=ru]
# Запускать из корня репо; тяжёлое — под `tools/ops/heavy-slot.sh`.
set -u
A=$1; B=$2; OUT=$3; N=${4:-5}; Q=${5:-?quiz=0&lang=ru}
mkdir -p "$OUT"
. tools/ops/node-env.sh
PA=$((8800 + RANDOM % 50)); PB=$((PA + 50))
STAGE=$A PORT=$PA NO_EVENTS=1 node tools/ops/demo-walk/stage-proxy.mjs > "$OUT/proxyA.log" 2>&1 & KA=$!
STAGE=$B PORT=$PB NO_EVENTS=1 node tools/ops/demo-walk/stage-proxy.mjs > "$OUT/proxyB.log" 2>&1 & KB=$!
trap 'kill $KA $KB 2>/dev/null' EXIT
sleep 2
for i in $(seq 1 "$N"); do
  for v in A:$PA B:$PB; do
    n=${v%%:*}; port=${v#*:}
    URL="http://127.0.0.1:$port/demo/$Q" NETW=slow4g NO3D=1 TAG="ab-$n$i" OUT="$OUT/" timeout 300 node tools/ops/demo-walk/page-measure.cjs > "$OUT/ab-$n$i.out" 2>&1
    echo "$n$i rc=$?"
  done
done
node -e '
const fs=require("fs"), path=require("path"), out=process.argv[1], n=+process.argv[2];
const K=["html","respEnd","dcl","data","ui","lcp","longtasksMs","kbToUi"];
const q=(a,p)=>{const s=[...a].sort((x,y)=>x-y); const i=(s.length-1)*p, lo=Math.floor(i), hi=Math.ceil(i); return Math.round(s[lo]+(s[hi]-s[lo])*(i-lo));};
const rows=["| метка | A медиана | A p75 | B медиана | B p75 | разница медиан |","|---|---|---|---|---|---|"], res={};
for (const v of ["A","B"]) res[v]=[...Array(n).keys()].map(i=>{try{return JSON.parse(fs.readFileSync(path.join(out,`ab-${v}${i+1}.json`),"utf8"));}catch{return null;}}).filter(Boolean);
for (const k of K) { const a=res.A.map(r=>r[k]).filter(x=>x>0), b=res.B.map(r=>r[k]).filter(x=>x>0); if(!a.length||!b.length)continue;
  rows.push(`| ${k} | ${q(a,.5)} | ${q(a,.75)} | ${q(b,.5)} | ${q(b,.75)} | ${q(b,.5)-q(a,.5)} |`); }
const errs=v=>res[v].flatMap(r=>r.errs||[]).length;
rows.push("", `прогонов: A ${res.A.length}, B ${res.B.length}; ошибок страницы: A ${errs("A")}, B ${errs("B")} (мс; kbToUi — КБ)`);
fs.writeFileSync(path.join(out,"summary.md"), rows.join("\n")+"\n"); console.log(rows.join("\n"));' "$OUT" "$N"
