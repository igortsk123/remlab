// Ответ клиенту письмом (П7): SMTP Яндекса, ящик palmarius.ru@yandex.ru (временно, решение владельца;
// брендовый ящик позже). Значения — ТОЛЬКО в /opt/remlab/.env; без них — no-op (деградация).

import nodemailer from "nodemailer";

export async function sendLeadEmail(to: string, subject: string, text: string): Promise<boolean> {
  const user = process.env.LEADS_SMTP_USER;
  const pass = process.env.LEADS_SMTP_PASS;
  if (!user || !pass || !to) return false;
  try {
    const transport = nodemailer.createTransport({
      host: process.env.LEADS_SMTP_HOST || "smtp.yandex.ru",
      port: Number(process.env.LEADS_SMTP_PORT || 465),
      secure: true,
      auth: { user, pass },
    });
    await transport.sendMail({ from: `remont-lab <${user}>`, to, subject, text });
    return true;
  } catch {
    return false;
  }
}
