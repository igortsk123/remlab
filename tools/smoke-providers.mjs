// Реальный смоук провайдеров ИИ (текст + генерация картинки).
// Запуск: pnpm smoke:providers  (читает GEMINI_API_KEY из .env.local через node --env-file).
// НЕ в CI — стоит денег и требует ключ. Печатает статус, картинку сохраняет в scratchpad tmp.

const KEY = process.env.GEMINI_API_KEY;
if (!KEY) {
  console.error("GEMINI_API_KEY не задан (нужен .env.local). Пропуск смоука.");
  process.exit(1);
}

const BASE = "https://generativelanguage.googleapis.com/v1beta";

async function gen(model, body) {
  const res = await fetch(`${BASE}/models/${model}:generateContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-goog-api-key": KEY },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${model}: HTTP ${res.status}`);
  return res.json();
}

const text = await gen("gemini-flash-latest", {
  contents: [{ parts: [{ text: "Reply with one word: OK" }] }],
});
const word = text?.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
console.log(`TEXT gemini-flash-latest → ${word}`);

const img = await gen("gemini-3.1-flash-image", {
  contents: [{ parts: [{ text: "cozy scandinavian living room, warm neutral palette" }] }],
  generationConfig: { responseModalities: ["IMAGE"] },
});
const inline = img?.candidates?.[0]?.content?.parts?.find((p) => p.inlineData)?.inlineData;
console.log(`IMAGE gemini-3.1-flash-image → ${inline ? `${inline.mimeType}, base64 ${inline.data.length} симв.` : "нет картинки"}`);

if (word !== "OK" || !inline) process.exit(1);
console.log("SMOKE OK");
