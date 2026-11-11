// Комнаты страницы тура в версии данных ↔ комнаты прочитанного плана (T-20261111-16): id страницы (`living`, `bedroom-1`), панель и
// id плана (ключ строк правок `<panel>|<src_id>`), вид, охват и право на фото этой версии. Для «Подтвердить планировку» (какие комнаты
// пересчёт задевает, галочки «размеры верны») и черновиков на странице (`GET edits`: строка правки → комната страницы).

type Box = { x: number; y: number; w: number; d: number };
type Bundle = {
  trial?: { panels?: { id: string; rooms?: { id: string; src_id?: unknown; kind?: string; bbox?: Box }[] }[] };
  apartment_rooms?: { id?: string; photo_ok?: unknown }[];
};
export type PageRoom = { id: string; panel: string; srcId: string; kind: string; bbox: Box; photoOk: boolean };

export function pageRooms(bundle: unknown): PageRoom[] {
  const b = bundle as Bundle;
  const photo = new Set((b?.apartment_rooms ?? []).filter((r) => r.photo_ok === true).map((r) => String(r.id)));
  return (b?.trial?.panels ?? []).flatMap((p) => (p.rooms ?? []).flatMap((r): PageRoom[] =>
    r.bbox && r.src_id !== undefined && r.src_id !== null
      ? [{ id: r.id, panel: p.id, srcId: String(r.src_id), kind: String(r.kind ?? "other"), bbox: r.bbox, photoOk: photo.has(r.id) }]
      : []));
}

/** Комната страницы по ключу строки правки (`<panel>|<src_id>`). */
export const roomByKey = (rooms: PageRoom[], key: string): PageRoom | undefined => rooms.find((r) => `${r.panel}|${r.srcId}` === key);

/** Комнаты панели, у чьей стены центр проёма (охват + `padCm`): пересчёт их задевает (точный список — у воркера, `opening_edits.dirty_rooms`). */
export const roomsAtOpening = (rooms: PageRoom[], panel: string, c: [number, number], padCm = 30): PageRoom[] =>
  rooms.filter((r) => r.panel === panel && c[0] >= r.bbox.x - padCm && c[0] <= r.bbox.x + r.bbox.w + padCm
    && c[1] >= r.bbox.y - padCm && c[1] <= r.bbox.y + r.bbox.d + padCm);
