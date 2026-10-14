"use client";

import { useEffect, useState } from "react";

import type { Lang } from "@/lib/configurator/i18n";

// «СВЯЗАТЬСЯ С МЕНЕДЖЕРОМ» В ПРАВОЙ ПАНЕЛИ 3D (план flat3d-sims-ux E3, b2b-02): только по ссылке менеджера (`?s=`).
// Тот же приём, что на демо (`tools/scout/flat215-demo/index.html: contactSheet`): каналы менеджера из его карточки
// (`/api/sends/:id`), текст сообщения уже написан, клик — сигнал менеджеру `manager_contact_click`. Без ссылки
// менеджера кнопки нет: свою форму с телефоном здесь не делаем (ПДн, b2b-04).
type Card = { manager: { name: string; phone?: string | null; telegram?: string | null; whatsapp?: string | null } };

export function ManagerContact({ sendId, lang, sum, items }: { sendId: string; lang: Lang; sum: number; items: string[] }) {
  const [card, setCard] = useState<Card | null>(null);
  const [open, setOpen] = useState(false);
  const en = lang === "en";

  useEffect(() => {
    let off = false;
    fetch(`/api/sends/${sendId}`, { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<{ card?: Card }>) : null))
      .then((j) => { if (!off && j?.card) setCard(j.card); })
      .catch(() => undefined); // нет карточки — нет кнопки, 3D работает
    return () => { off = true; };
  }, [sendId]);

  if (!card) return null;
  const M = card.manager;
  const text = en
    ? `Hello, ${M.name}! I am looking at the apartment in 3D from your link, upgrades for ${sum.toLocaleString("en-GB")}. I would like some advice. ${location.href}`
    : `Здравствуйте, ${M.name}! Смотрю квартиру в 3D по вашей ссылке, доплата за выбор ${sum.toLocaleString("ru-RU")}. Хочу консультацию. ${location.href}`;
  const links: [string, string, string][] = [];
  if (M.whatsapp) links.push(["whatsapp", "WhatsApp", `https://wa.me/${M.whatsapp.replace(/\D/g, "")}?text=${encodeURIComponent(text)}`]);
  if (M.telegram) links.push(["telegram", "Telegram", `https://t.me/${encodeURIComponent(M.telegram.replace(/^@/, ""))}?text=${encodeURIComponent(text)}`]);
  if (M.phone) links.push(["phone", (en ? "Call " : "Позвонить ") + M.phone, `tel:${M.phone.replace(/[^\d+]/g, "")}`]);
  if (!links.length) return null;

  const signal = (channel: string) => {
    const body = JSON.stringify({ kind: "manager_contact_click", purpose: "consult", channel, sum: Math.round(sum), items: items.slice(0, 10) });
    const url = `/api/sends/${sendId}/event`;
    // sendBeacon переживает уход в мессенджер: обычный запрос при переходе обрывается
    try {
      if (navigator.sendBeacon?.(url, new Blob([body], { type: "application/json" }))) return;
    } catch { /* нет sendBeacon — обычный запрос */ }
    fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body, keepalive: true }).catch(() => undefined);
  };

  return (
    <div className="mt-2">
      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="min-h-11 w-full rounded-lg bg-brand-solid px-3 text-sm font-semibold text-white">
          {en ? `Contact ${M.name}` : `Связаться с менеджером · ${M.name}`}
        </button>
      ) : (
        <div className="flex flex-col gap-2">
          <span className="text-tertiary">{(M.whatsapp || M.telegram)
            ? (en ? "The message is already written — just send it." : "Сообщение уже написано — останется отправить.")
            : (en ? "Call — your manager sees what you looked at." : "Позвоните — менеджер видит, что вы смотрели.")}</span>
          {links.map(([ch, label, href]) => (
            <a key={ch} href={href} target="_blank" rel="noopener" onClick={() => signal(ch)}
              className="min-h-11 rounded-lg bg-brand-solid px-3 py-3 text-center text-sm font-semibold text-white">{label}</a>
          ))}
        </div>
      )}
    </div>
  );
}
