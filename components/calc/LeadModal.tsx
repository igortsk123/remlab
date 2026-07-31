"use client";

// Единая модалка «Найдём дешевле» (П7): для всех трёх каналов — город (автокомплит по справочнику РФ);
// для почты — плюс e-mail. После отправки: почта — «спасибо»; TG/MAX — кнопки «Подписаться…» с
// deep-link `/start <код заявки>` (боты не могут писать первым — нужен Start; решение владельца:
// показываем ОБЕ кнопки). Закрытие: backdrop, «×», Esc.

import { useRef, useState, useTransition } from "react";
import type { CalcKind } from "@/contracts/calc";
import { captureLead } from "@/app/lead-actions";
import { Button } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { Dialog, Modal, ModalOverlay } from "@/components/application/modals/modal";

const TG_BOT = process.env.NEXT_PUBLIC_TELEGRAM_BOT;
const MAX_BOT = process.env.NEXT_PUBLIC_MAX_BOT;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export type LeadChannel = "email" | "tg" | "max";

type CityHit = { name: string; region: string };

export function LeadModal({ kind, url, channel, onClose }: { kind: CalcKind; url?: string; channel: LeadChannel; onClose: () => void }) {
  const [city, setCity] = useState("");
  const [hits, setHits] = useState<CityHit[]>([]);
  const [showHits, setShowHits] = useState(false);
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [done, setDone] = useState<{ leadNo: number | null; startCode: string } | null>(null);
  const [error, setError] = useState(false);
  const [pending, startTransition] = useTransition();
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const needEmail = channel === "email";
  const emailOk = !needEmail || EMAIL_RE.test(email.trim());
  const cityOk = city.trim().length >= 2;

  // Автокомплит города: подсказки с сервера (справочник ~1100 городов РФ).
  function onCity(v: string) {
    setCity(v);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(async () => {
      if (v.trim().length < 2) { setHits([]); return; }
      try {
        const res = await fetch(`/api/leads/cities?q=${encodeURIComponent(v.trim())}`);
        const data = await res.json();
        setHits(Array.isArray(data?.cities) ? data.cities : []);
        setShowHits(true);
      } catch { setHits([]); }
    }, 250);
  }

  function submit() {
    if (!cityOk || !emailOk || !consent) return;
    setError(false);
    startTransition(async () => {
      const res = await captureLead({ channel, email: needEmail ? email.trim() : undefined, city: city.trim(), urls: url ? [url] : undefined, kind, consent });
      if (res.ok) setDone({ leadNo: res.leadNo, startCode: res.startCode });
      else setError(true);
    });
  }

  const tgHref = TG_BOT && done ? `https://t.me/${TG_BOT}?start=${done.startCode}` : null;
  const maxHref = MAX_BOT && done ? `https://max.ru/${MAX_BOT}?start=${done.startCode}` : null;

  return (
    <ModalOverlay isOpen isDismissable onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal className="max-w-[420px]">
        <Dialog aria-label="Найдём дешевле" className="relative p-6">
        <CloseButton label="Закрыть" className="absolute top-2 right-2" onClick={onClose} />
        {done ? (
          <div className="stack" style={{ gap: 10 }}>
            <p style={{ margin: 0 }}>
              Заявка{done.leadNo ? ` #${done.leadNo}` : ""} принята! Ищем, где дешевле в вашем городе.
            </p>
            {channel === "email" ? (
              <p className="muted" style={{ margin: 0, fontSize: 14 }}>Пришлём варианты на почту.</p>
            ) : (
              <>
                <p className="muted" style={{ margin: 0, fontSize: 14 }}>
                  Чтобы мы могли вам написать, подпишитесь на бота и нажмите в нём <strong>Start</strong> — без этого мессенджер не даёт боту отправить сообщение.
                </p>
                <div className="row" style={{ gap: 8 }}>
                  {tgHref
                    ? <Button color="secondary" size="md" href={tgHref} target="_blank" rel="noopener noreferrer">Подписаться в Телеграм</Button>
                    : <Button type="button" color="secondary" size="md" isDisabled>Телеграм скоро</Button>}
                  {maxHref
                    ? <Button color="secondary" size="md" href={maxHref} target="_blank" rel="noopener noreferrer">Подписаться в MAX</Button>
                    : <Button type="button" color="secondary" size="md" isDisabled>MAX скоро</Button>}
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            <p className="eyebrow" style={{ margin: 0 }}>Найдём дешевле</p>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>Где искать? Укажите город — сравним магазины рядом с вами и онлайн.</p>

            <div style={{ position: "relative" }}>
              <Input
                size="md"
                placeholder="Ваш город"
                value={city}
                onChange={onCity}
                onFocus={() => hits.length && setShowHits(true)}
                aria-label="Ваш город"
              />
              {showHits && hits.length > 0 && (
                <div className="city-hits">
                  {hits.map((h) => (
                    <button key={`${h.name}|${h.region}`} type="button" onClick={() => { setCity(h.name); setShowHits(false); }}>
                      {h.name} <span className="muted">· {h.region}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {needEmail && (
              <Input size="md" type="email" inputMode="email" placeholder="E-mail для ответа" value={email} onChange={setEmail} aria-label="E-mail для ответа" />
            )}

            <Checkbox
              isSelected={consent}
              onChange={setConsent}
              label={
                <span className="muted" style={{ fontSize: 13 }}>
                  Я согласен с <a href="#" onClick={(e) => e.preventDefault()}>политикой обработки персональных данных</a>.
                </span>
              }
            />

            <Button type="button" size="md" isDisabled={pending || !cityOk || !emailOk || !consent} isLoading={pending} showTextWhileLoading onClick={submit}>
              {pending ? "Отправляем…" : "Отправить заявку"}
            </Button>
            {needEmail && email.length > 0 && !emailOk && <span className="muted" style={{ fontSize: 13 }}>Проверьте формат e-mail.</span>}
            {error && <span className="muted" style={{ fontSize: 13 }}>Не удалось отправить, попробуйте ещё раз.</span>}
          </div>
        )}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
