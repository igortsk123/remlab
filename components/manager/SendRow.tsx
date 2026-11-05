"use client";

import { useState } from "react";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { ACTION_LABEL, STATUS_LABEL, type ManagerSendRow } from "@/components/manager/types";
import { cleanGreetName, linkWithName } from "@/lib/quiz/name";

const NOTE_KEY = (id: string) => `remlab-send-note:${id}`;
const readNote = (id: string) => { try { return localStorage.getItem(NOTE_KEY(id)) ?? ""; } catch { return ""; } };
// Имя для приветствия опроса (onb-03 Т2, ADR-0330 п.4): только в этом браузере до конца сессии, в ссылку — `#n=`, на сервер не уходит.
const NAME_KEY = (id: string) => `remlab-send-name:${id}`;
const readName = (id: string) => { try { return sessionStorage.getItem(NAME_KEY(id)) ?? ""; } catch { return ""; } };
// TODO(onb-03 Т1): показывать поле по флагу квартиры `apartments[].quiz.enabled` (`contracts/partner.ts`, вливает другой рабочий) —
// через `ManagerData.apartments[].quiz`; до того поле выключено.
const QUIZ_NAME_FIELD = false;
const date = (s: string) => new Date(s).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

// Одна ссылка: заметка «кому» (только в этом браузере), статус, что делал покупатель, дошли ли сигналы.
export function SendRow({ row, onStatus }: { row: ManagerSendRow; onStatus: (id: string, body: object) => void }) {
  const [note, setNote] = useState(() => readNote(row.id));
  const [name, setName] = useState(() => (QUIZ_NAME_FIELD ? readName(row.id) : ""));
  const [copied, setCopied] = useState(false);
  const save = (v: string) => { setNote(v); try { localStorage.setItem(NOTE_KEY(row.id), v); } catch { /* приватный режим */ } };
  const saveName = (v: string) => { setName(v); setCopied(false); try { sessionStorage.setItem(NAME_KEY(row.id), v); } catch { /* приватный режим */ } };
  const badName = name.trim() !== "" && !cleanGreetName(name);
  const copy = async () => { try { await navigator.clipboard.writeText(linkWithName(row.url, name)); setCopied(true); } catch { setCopied(false); } };
  const counts = row.actions.reduce<Record<string, number>>((a, e) => ({ ...a, [e.kind]: (a[e.kind] ?? 0) + 1 }), {});

  return (
    <div className="card stack" style={{ gap: 8, opacity: row.revoked ? 0.55 : 1 }}>
      <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <strong>{note || `Ссылка от ${date(row.createdAt)}`}</strong>
        <Badge type="pill-color" color={row.status === "deal" ? "success" : row.status === "lost" ? "gray" : "brand"} size="sm">
          {row.revoked ? "отозвана" : STATUS_LABEL[row.status] ?? row.status}
        </Badge>
      </div>
      <Input size="sm" placeholder="Кому ссылка — видно только вам" value={note} onChange={save} />
      {QUIZ_NAME_FIELD && !row.revoked && (
        <Input size="sm" label="Имя для приветствия" placeholder="Анна" value={name} onChange={saveName} isInvalid={badName}
          hint={badName ? "Только буквы, пробел и дефис, до 30 знаков — иначе страница скажет просто «Здравствуйте!»" : "Страница поздоровается по имени. Имя не уходит к нам на сервер"} />
      )}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <Button size="sm" color="secondary" onClick={copy}>{copied ? "Скопировано" : "Скопировать ссылку"}</Button>
        {!row.revoked && <span className="muted" style={{ fontSize: 14, alignSelf: "center" }}>Отметить:</span>}
        {!row.revoked && (["contacted", "meeting", "deal", "lost"] as const).map((st) => (
          <Button key={st} size="sm" color="tertiary" onClick={() => onStatus(row.id, { status: st })}>{STATUS_LABEL[st]}</Button>
        ))}
        {!row.revoked && <Button size="sm" color="link-gray" onClick={() => onStatus(row.id, { revoke: true })}>Отозвать</Button>}
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>
        {Object.keys(counts).length
          ? Object.entries(counts).map(([k, n]) => `${ACTION_LABEL[k] ?? k}${n > 1 ? ` ×${n}` : ""}`).join(" · ")
          : "Покупатель ещё не открывал."}
        {row.signals.noChannel > 0 && ` · сигналов без Telegram: ${row.signals.noChannel}`}
        {row.signals.failed > 0 && ` · не доставлено (бот заблокирован?): ${row.signals.failed}`}
      </p>
    </div>
  );
}
