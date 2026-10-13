// Номер телефона к одному виду — только цифры с кодом страны (план b2b-02). Менеджер делится
// номером из Telegram («+7 913…», «8913…», «07700…»), застройщик присылает список как попало —
// сравнивать можно только нормализованное. Та же логика — в `infra/server/manager-add.sh`.

export function normalizePhone(raw: string): string | null {
  let d = String(raw ?? "").replace(/\D/g, "");
  if (d.length === 11 && d.startsWith("8")) d = `7${d.slice(1)}`; // РФ: 8XXXXXXXXXX
  else if (d.length === 10 && d.startsWith("9")) d = `7${d}`; // РФ без кода
  else if (d.length === 11 && d.startsWith("07")) d = `44${d.slice(1)}`; // UK мобильный 07…
  return d.length >= 11 && d.length <= 15 ? d : null;
}
