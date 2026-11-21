"""Ш6: почему вар.2 (trellis_relief) в far/side не меняет ни Брера, ни Денди (цифры вар.2 = «сейчас» до сотых)? Для двух масок на замороженном v2 — прогнать fill с черновиком и напечатать, ЧТО решил рельеф по части-мишени:
rep['relief'] (по частям: источник/причина отказа/калибровка), texture_src, relief_texels, quilt_info части. Без метрик, один прогон на запись (зеркало выкл)."""
import json
import os
import sys

W = os.path.expanduser('~/remlab-logs/t182-1121/tools/scout/salad/trellis')
for q in (W, W + '/..', W + '/../..', W + '/../../stablegen'):
    sys.path.insert(0, q)
import numpy as np
import tex_coverage as TC
import tex_fill as TF
import tex_fill_blind as BL

FD = os.path.expanduser('~/remlab-logs/t182-1121/blind-v2/frozen')
DR = os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis2')
fz = json.load(open(FD + '/frozen.json', encoding='utf-8'))
BL.PARAMS.update(fz['params'])
Z = np.load(FD + '/masks.npz')
WANT = [('112923_16411672175141188566', 'far'), ('114082_10587794773481498560', 'side'), ('112923_10551627698909366429', 'far')]
for it in fz['items']:
    root, sku = it['root'], it['sku']
    for mode, md in it['modes'].items():
        if (sku, mode) not in WANT or 'skipped' in md:
            continue
        vis, npz, geoms, known, parts, txs = BL.load_item(root, sku)
        cfgb, note = TF.resolve_part_class({'source': 'trellis_relief', 'relief_calib_donor': True}, npz if os.path.exists(npz) else None, os.path.exists(npz))
        cfgb = dict(cfgb, erode_known=0)
        hidden = []
        for gi, tx in enumerate(txs):
            k = f'{sku}|{mode}|{gi}'
            shp = tuple(Z[k + '|shape'])
            hidden.append(np.unpackbits(Z[k])[:shp[0] * shp[1]].astype(bool).reshape(shp))
        geoms_h, kn_h = [], []
        for gi, g in enumerate(geoms):
            tex = np.asarray(g['tex']).copy()
            tex[hidden[gi]] = 0
            geoms_h.append(dict(g, tex=tex))
            kn_h.append(known[gi] & ~hidden[gi])
        dg = TC.load_geoms(f'{DR}/{sku}-1024-42-0.glb')
        cfgd = dict(cfgb, source='trellis_relief')
        dr = TF.draft_texels(geoms_h, dg, cfgd)
        res = TF.fill(geoms_h, kn_h, parts, cfg=cfgd, mirror=False, draft=dr)
        rep = res['report']
        part = it['part']
        print(f'== {sku} · {mode} · мишень ч.{part} · {note}', flush=True)
        print('  source_used', rep.get('source_used'), '| source_tried', rep.get('source_tried'), '| relief_texels', rep.get('relief_texels'), flush=True)
        print('  relief (всё):', json.dumps(rep.get('relief'), ensure_ascii=False, default=str)[:1800], flush=True)
        print('  texture_src мишени:', (rep.get('texture_src') or {}).get(part), '| quilt_info мишени:', json.dumps((rep.get('quilt_info') or {}).get(part), ensure_ascii=False, default=str)[:600], flush=True)
        print('  part_class мишени:', (cfgd.get('part_class') or {}).get(part, (cfgd.get('part_class') or {}).get(str(part))), '| pattern:', (rep['parts'].get(part) or {}).get('pattern'), flush=True)
