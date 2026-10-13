// Что видит менеджер на своей странице (план b2b-02): его ссылки, статусы, что делал покупатель
// и дошли ли сигналы. Заметок «кому ссылка» здесь нет — они живут только в браузере менеджера.

import { apartmentsOf, sendUrl } from "@/modules/sends/apartments";
import { MANAGER_TG_TOKEN } from "@/modules/sends/dispatch";
import { sendStore } from "@/modules/sends/service";
import type { Manager, SendStore } from "@/modules/sends/types";

export async function managerView(m: Manager, store: SendStore = sendStore()) {
  const sends = await store.listSends(m.id, 100);
  const outbox = await store.outboxFor(sends.map((s) => s.id));
  const rows = await Promise.all(sends.map(async (s) => {
    const ev = await store.events(s.id, 50);
    const sig = outbox.filter((o) => o.sendId === s.id);
    return {
      id: s.id, url: sendUrl(s.id), apartmentId: s.apartmentId, status: s.status, revoked: s.revoked,
      createdAt: s.createdAt, openedAt: s.openedAt, createdVia: s.createdVia,
      actions: ev.filter((e) => e.kind !== "status").map((e) => ({ kind: e.kind, at: e.createdAt })),
      signals: {
        sent: sig.filter((o) => o.status === "sent").length,
        noChannel: sig.filter((o) => o.status === "no_channel").length,
        failed: sig.filter((o) => o.status === "failed").length,
        pending: sig.filter((o) => o.status === "pending").length,
      },
    };
  }));
  return {
    manager: { name: m.displayName, telegramConnected: !!m.tgChatId && !!MANAGER_TG_TOKEN() },
    apartments: apartmentsOf(m.partnerId),
    sends: rows,
  };
}
