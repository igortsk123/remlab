// Типы, общие для сервера и клиента /lab/mesh-audit (без импорта БД — их видит браузерный код).

export interface AuditItemView {
  id: number;
  sku: string;
  generationKey: string;
  role: string | null;
  name: string | null;
  imageUrl: string | null;
  posterUrl: string | null;
  modelPath: string;
  seed: number | null;
  attempt: number | null;
  generatedAt: string | null; // ISO
  photoStale: boolean;
  variantsNote: string | null; // «+4 варианта: …» — карточка представителя семейства моделей
  manualAttempts: number;
  status: string;
  reworkStatus: string | null;
  reworkError: string | null;
  redoneAt: string | null;
  seenAt: string | null;
  // страница проверки /lab/mesh-check (T-20261112-118): текущее состояние по ТЕКУЩЕМУ поколению; журнал — mesh_audit_marks/notes
  posterHdUrl: string | null; // снимок 1024 px для увеличения
  mark: string | null; // ok | bad | null
  markBy: string | null;
  note: string | null;
  noteSeq: number | null;
}

export interface BatchView {
  id: number;
  batch: number;
  token: string;
  status: string;
  filesTotal: number | null;
  filesDone: number | null;
  bytesTotal: number | null;
  error: string | null;
  activatedAt: string | null; // ISO — от него публикатор считает grace перед удалением предыдущей
}

export interface BatchStateView {
  active: BatchView | null; // отдаётся с сервера
  retiring: BatchView | null; // ещё лежит, скоро удалится (grace после смены)
  pending: BatchView | null; // запрошена / льётся / проверяется
}
