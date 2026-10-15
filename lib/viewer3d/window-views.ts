// ВИД ИЗ ОКНА — НАШ НАБОР ПО УМОЛЧАНИЮ (план demo-04 п.5). Застройщик выбирает вид в карточке квартиры
// (`data/partners/*.json` → `windowView`), пока своего вида у него нет. Картинки — `public/scene/views/<id>.webp`
// (сделаны генерацией, `tools/scene/window_views.py`), `horizon01` — где горизонт, доля высоты от верха (замер глазами 14.10):
// плоскость вида ставится так, чтобы горизонт был на уровне глаз. Серверный кадр берёт ту же картинку по id
// (`tools/scout/opening_ir.py`), произвольные адреса сюда не попадают.

export interface WindowView {
  url: string;
  horizon01: number;
  aspect: number;
}

const ASPECT = 1600 / 1072;

export const WINDOW_VIEWS: Record<string, WindowView> = {
  "city-day": { url: "/scene/views/city-day.webp", horizon01: 0.28, aspect: ASPECT },
  "city-evening": { url: "/scene/views/city-evening.webp", horizon01: 0.39, aspect: ASPECT },
  yard: { url: "/scene/views/yard.webp", horizon01: 0.35, aspect: ASPECT },
  park: { url: "/scene/views/park.webp", horizon01: 0.45, aspect: ASPECT },
};

export const DEFAULT_WINDOW_VIEW = "yard";

/** Вид по id из карточки; неизвестный id — вид по умолчанию (чужой адрес сюда не проходит). */
export function windowView(id: string | undefined): { id: string; view: WindowView } {
  const key = id && WINDOW_VIEWS[id] ? id : DEFAULT_WINDOW_VIEW;
  return { id: key, view: WINDOW_VIEWS[key]! };
}
