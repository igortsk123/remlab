"""T-118: наполнить ВРЕМЕННУЮ БД t118-pg (снимки страницы) реальными карточками DEV (только чтение БД DEV).
Постеры — абсолютные ссылки на прод (там они лежат); SQL — в файл, применяет docker exec psql."""
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/tools/scout')
import mesh_audit_sync as S  # noqa: E402

PROD = 'https://remont-lab.online'


def q(v):
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


items = S.current_items()
out = sys.argv[1]
with open(out, 'w') as f:
    f.write('begin;\n')
    for i in items:
        poster = PROD + i['posterUrl'] if i.get('posterUrl') else None
        cols = ['sku', 'generation_key', 'role', 'name', 'image_url', 'poster_url', 'model_path', 'seed', 'attempt', 'variants_note']
        vals = [i['sku'], i['generationKey'], i.get('role'), i.get('name'), i.get('imageUrl'), poster, i['modelPath'],
                i.get('seed'), i.get('attempt'), i.get('variantsNote')]
        f.write(f"insert into mesh_audit_items ({', '.join(cols)}) values ({', '.join(q(v) for v in vals)}) on conflict (sku) do nothing;\n")
    f.write('commit;\n')
print('items', len(items), 'with poster', sum(1 for i in items if i.get('posterUrl')), out)
