// Типы /lab/cutout-check, общие для сервера и браузера (без импорта БД).

export interface CutoutItemView {
  id: number;
  run: string;
  sku: string;
  position: number;
  role: string | null;
  name: string | null;
  nameEn: string | null;
  shop: string | null;
  shopUrl: string | null;
  photoUrl: string | null; // фото магазина (как резали)
  cutUrl: string | null; // вырезка с прозрачностью
  generationKey: string; // отпечаток вырезки: новая вырезка — другой ключ, отметка сбрасывается
  info: Record<string, unknown> | null; // вердикт цепочки, размеры
  mark: string | null; // ok | bad | null
  markBy: string | null;
  viewedAt: string | null; // ISO: карточка побыла на экране ≥ 1 с
  note: string | null;
  noteSeq: number | null;
}

export interface RoleCount {
  role: string;
  total: number;
  checked: number;
  bad: number;
}
