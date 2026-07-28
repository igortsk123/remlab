import { describe, it, expect } from "vitest";
import { formatIncoming, formatLeadCard } from "@/lib/leads/router";
import { searchCities, cityExists } from "@/lib/leads/cities";
import { leadRepo } from "@/modules/leads/repository";

describe("П7 лид-канал", () => {
  it("карточка заявки: номер, канал, город, товар, инструкция реплая", () => {
    const card = formatLeadCard({ id: "x", leadNo: 7, channel: "tg", city: "Кемерово", kind: "oboi", url: "https://shop/oboi", sessionId: "s" });
    expect(card).toContain("Заявка #7 · Телеграм");
    expect(card).toContain("Город: Кемерово");
    expect(card).toContain("Калькулятор: Обои");
    expect(card).toContain("https://shop/oboi");
    expect(card).toContain("РЕПЛАЕМ");
  });

  it("подпись входящего от клиента содержит номер заявки", () => {
    expect(formatIncoming({ id: "x", leadNo: 3, channel: "email", sessionId: "s" }, "есть дешевле?")).toContain("Заявка #3");
  });

  it("справочник городов: префикс, ё≈е, короткий запрос пуст", () => {
    expect(searchCities("моск").some((c) => c.n === "Москва")).toBe(true);
    expect(searchCities("орел").some((c) => c.n === "Орёл")).toBe(true);
    expect(searchCities("м")).toEqual([]);
    expect(cityExists("Москва")).toBe(true);
    expect(cityExists("Хогвартс")).toBe(false);
  });

  it("memory-репозиторий: create→leadNo, привязка чата, reply-маппинг по admin message id", async () => {
    const repo = leadRepo();
    const a = await repo.create({ channel: "tg", city: "Томск", sessionId: "s1" });
    const b = await repo.create({ channel: "email", email: "a@b.ru", city: "Омск", sessionId: "s2" });
    expect(a.leadNo).toBe(1);
    expect(b.leadNo).toBe(2);
    await repo.setChat(a.id, "chat42");
    expect((await repo.byChat("chat42"))?.id).toBe(a.id);
    await repo.addMessage({ leadId: b.id, direction: "in", text: "(заявка)", adminTgMessageId: 555 });
    expect((await repo.byAdminMsg(555))?.id).toBe(b.id);
    expect(await repo.byAdminMsg(999)).toBeNull();
  });
});
