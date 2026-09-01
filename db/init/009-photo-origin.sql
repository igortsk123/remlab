-- ПРОИСХОЖДЕНИЕ ФОТО: каталожная карточка или рекламный коллаж (решение владельца 01.09).
--
-- «Пусть модель делает такое, просто помечай все меши в базе, которые из коллажей сделаны».
-- Раньше такое фото просто отклонялось (BadCutout) и товар выпадал из очереди молча. Теперь
-- меш генерируем всегда, а происхождение храним — чтобы потом отсортировать и пересмотреть
-- те модели, у которых вход был заведомо грязный.
--
-- Признак считает `tools/scout/photo_bg.py` по САМОМУ ФОТО, без нейросети вырезки: у
-- каталожной карточки фон белый и ровный, у коллажа — сцена, плашки, текст.

alter table products add column if not exists photo_bg text;          -- white|scene|unknown
alter table products add column if not exists photo_bg_score real;    -- доля белого по рамке
-- НЕ вердикт «это коллаж», а метка «фон не белый → на проверку человеком»
alter table products add column if not exists photo_collage boolean;
alter table products add column if not exists photo_bg_at timestamptz;

-- Меш, сделанный из фото с небелым фоном. Сам меш может быть и хорошим — метка нужна,
-- чтобы такие модели можно было отобрать и просмотреть, а не открывать это заново.
alter table products add column if not exists mesh_from_collage boolean;

create index if not exists products_photo_collage_idx on products (photo_collage)
  where photo_collage;
create index if not exists products_mesh_from_collage_idx on products (mesh_from_collage)
  where mesh_from_collage;
