// Ответ `GET /api/manager` (см. `modules/sends/manager-view.ts`) в том виде, как его видит браузер.
export type ManagerSendRow = {
  id: string;
  url: string;
  apartmentId: string;
  status: string;
  revoked: boolean;
  createdAt: string;
  openedAt: string | null;
  actions: { kind: string; at: string }[];
  signals: { sent: number; noChannel: number; failed: number; pending: number };
};
export type ManagerData = {
  manager: { name: string; telegramConnected: boolean };
  apartments: { id: string; title: string }[];
  sends: ManagerSendRow[];
};

export const STATUS_LABEL: Record<string, string> = {
  sent: "отправлена", opened: "открыл", engaged: "выбирает", contacted: "связались",
  meeting: "встреча", deal: "сделка", lost: "отказ",
};
export const ACTION_LABEL: Record<string, string> = {
  designer_open: "открыл", variant_view: "смотрел вариант", item_swap: "менял мебель", item_move: "передвигал мебель", share: "поделился", floor_pick: "выбирал пол",
  manager_contact_click: "нажал «связаться»", alternative_request: "просил другой вариант",
};
