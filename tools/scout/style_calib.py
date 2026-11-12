"""Поправка балла стиля по признакам фида (T-20261112-119, `rules/style-calibration.json`).

Слой поверх балла style_score.py (LLM + правила + CLIP): узкие правила по названию и параметрам фида и сдвиг шкалы по стилю —
так, чтобы общий порог «в стиле» 6,6 (demo-swap.json) значил для каждого стиля то же, что у человека. Порог в потребителях не меняется.

Где действует: гостиная — `product_style_scores` (ленты замен /demo, demo_band → очередь мешей). Банк гостиной оценивает стиль по
обогащению (enrich_bridge) — его эта поправка не меняет. Спальня и прихожая — нет (разметка была по гостиной).

Запуск:
  python style_calib.py            — снимок «было|стало» по базе (ничего не пишет)
  python style_calib.py --apply    — разово переписать строки гостиной без метки версии (только при enabled=true)
Метка версии — в `src` строки (`…+cal:<version>`): повторный --apply и ночная запись не правят строку дважды.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A',
        '-F', '\x1f']


def load(path: str | None = None) -> dict:
    return json.load(open(path or os.path.join(HERE, 'rules', 'style-calibration.json'), encoding='utf-8'))


def mark(cfg: dict) -> str:
    return f"cal:{cfg['version']}"


def calibrated(src: str | None, cfg: dict) -> bool:
    """Строка уже поправлена этой версией (src несёт метку)."""
    return mark(cfg) in (src or '')


def features_text(name: str, params: dict | None, cfg: dict) -> str:
    keys = re.compile(cfg['text_param_keys'], re.I)
    keep = ' '.join(f'{k} {v}' for k, v in (params or {}).items() if keys.search(str(k)))
    return f'{name or ""} {keep}'.lower()


def apply(scores: dict, role: str, name: str, params: dict | None, cfg: dict) -> tuple[dict, list[str]]:
    """Балл после правил и сдвига (0–10) + id сработавших правил. Прочие ключи (universal и т.п.) — как были."""
    out = dict(scores)
    t = features_text(name, params, cfg)
    not_hard = set(cfg.get('not_hard_roles') or [])
    fired = []
    for r in cfg['rules']:
        if r.get('hard_only') and (role or '') in not_hard:
            continue
        if r.get('roles') and role not in r['roles']:
            continue
        if r.get('if') and not re.search(r['if'], t):
            continue
        if r.get('unless') and re.search(r['unless'], t):
            continue
        fired.append(r['id'])
        for st, d in r['delta'].items():
            if st in out:
                out[st] = max(0.0, min(10.0, float(out[st]) + d))
    for st, d in (cfg.get('offsets') or {}).items():
        if st in out:
            out[st] = max(0.0, min(10.0, float(out[st]) + d))
    for st in STYLES:
        if st in out:
            out[st] = round(float(out[st]), 1)
    return out, fired


def _rows(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'СТОП: запрос к базе — {r.stderr[:300]}')
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def params_of(pairs: list[tuple[int, str]]) -> dict:
    """(mid, eid) → (role, name, params) из products — для поправки при записи style_score."""
    out = {}
    for i in range(0, len(pairs), 2000):
        vals = ','.join(f"({int(m)},'{str(e).replace(chr(39), chr(39) * 2)}')" for m, e in pairs[i:i + 2000])
        for m, e, role, name, pj in _rows(f"with v(m,e) as (values {vals}) select v.m, v.e, coalesce(p.cat_role,''), coalesce(p.name,''), "
                                          f"coalesce(p.params::text,'{{}}') from v join products p on p.shop_mid=v.m and p.external_id=v.e"):
            try:
                pr = json.loads(pj)
            except ValueError:
                pr = {}
            out[(int(m), e)] = (role, name, pr)
    return out


def living_rows() -> list[tuple]:
    """Строки гостиной в базе: (mid, eid, role, name, params, scores, src). Гостиная = src без пометок спальни/прихожей —
    style_score пишет гостиную без keep, спальня/прихожая — keep (чужие строки не трогают); роли гостиной — из profiles/living.json."""
    roles = sorted(json.load(open(os.path.join(HERE, 'rules', 'profiles', 'living.json'), encoding='utf-8')).get('roles') or [])
    lit = ','.join("'" + r.replace("'", "''") + "'" for r in roles) if roles else "''"
    out = []
    for m, e, role, name, pj, sc, src in _rows(
            "select s.shop_mid, s.external_id, coalesce(p.cat_role,''), coalesce(p.name,''), coalesce(p.params::text,'{}'), "
            "s.scores::text, coalesce(s.src,'') from product_style_scores s join products p "
            f"on p.shop_mid=s.shop_mid and p.external_id=s.external_id where p.cat_role in ({lit})"):
        try:
            pr = json.loads(pj)
        except ValueError:
            pr = {}
        out.append((int(m), e, role, name, pr, json.loads(sc), src))
    return out


def main() -> int:
    cfg = load()
    thr = float(json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))['in_style_min'])
    rows = living_rows()
    was = {st: 0 for st in STYLES}
    now = {st: 0 for st in STYLES}
    changed = done = 0
    upd = []
    fired_n: dict = {}
    for m, e, role, name, pr, sc, src in rows:
        if not all(st in sc for st in STYLES):
            continue
        if calibrated(src, cfg):
            done += 1
            continue
        new, fired = apply(sc, role, name, pr, cfg)
        for f in fired:
            fired_n[f] = fired_n.get(f, 0) + 1
        a = {st for st in STYLES if float(sc[st]) >= thr}
        b = {st for st in STYLES if new[st] >= thr}
        changed += a != b
        for st in STYLES:
            was[st] += st in a
            now[st] += st in b
        upd.append((m, e, new, f'{src}+{mark(cfg)}'))
    print(f'поправка {cfg["version"]} (enabled={cfg["enabled"]}): строк гостиной {len(rows)}, уже с меткой {done}, '
          f'к поправке {len(upd)}, меняют набор стилей {changed}')
    print('сработало правил:', fired_n)
    for st in STYLES:
        print(f'  {st:12} «в стиле» (≥{thr:g}) {was[st]} → {now[st]} ({now[st] - was[st]:+d})')
    if '--apply' not in sys.argv:
        print('снимок: база не тронута (запись — --apply при enabled=true)')
        return 0
    if not cfg['enabled']:
        print('СТОП: rules/style-calibration.json enabled=false — включает директор после снимка «было|стало»')
        return 2
    n = 0
    for i in range(0, len(upd), 1000):
        vals = []
        for m, e, sc, src in upd[i:i + 1000]:
            st6 = {st: sc[st] for st in STYLES}
            js = json.dumps({**sc}, ensure_ascii=False).replace("'", "''")
            vals.append(f"({m},'{e.replace(chr(39), chr(39) * 2)}','{js}'::jsonb,'{max(st6, key=st6.get)}','{src.replace(chr(39), chr(39) * 2)}')")
        _rows("update product_style_scores s set scores=v.sc, top_style=v.top, src=v.src from (values " + ','.join(vals) +
              ") as v(m,e,sc,top,src) where s.shop_mid=v.m and s.external_id=v.e")
        n += len(vals)
    print(f'OK: поправлено строк {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
