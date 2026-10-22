import { describe, expect, it } from "vitest";

import { shopStripper } from "@/lib/configurator/label";

// Подпись товара в кадре /flat — без магазина (flat3d-375-overlaps): домен из названия убирается, остальное — как было
describe("shopStripper", () => {
  const strip = shopStripper(["divan.ru", "tvoydom.ru", "divanboss.ru", "mnogomebeli.com"]);

  it("домен посреди названия", () => {
    expect(strip("Диван прямой divan.ru Викс Рогожка Голубой")).toBe("Диван прямой Викс Рогожка Голубой");
    expect(strip("ТВ-тумба divan.ru Теджонс 139x62 Ромб Латте")).toBe("ТВ-тумба Теджонс 139x62 Ромб Латте");
  });

  it("английское название через точку-разделитель", () => {
    expect(strip("Sofa · divan.ru")).toBe("Sofa");
    expect(strip("tvoydom.ru · Стул разборный TC")).toBe("Стул разборный TC");
  });

  it("варианты домена: регистр, www, пробел вместо точки, одно имя", () => {
    expect(strip("Кресло DIVAN.RU Ньюбери")).toBe("Кресло Ньюбери");
    expect(strip("www.Divan.ru · Диван")).toBe("Диван");
    expect(strip("Кресло divan ru Ньюбери")).toBe("Кресло Ньюбери");
    expect(strip("Стол TvoyDom Прованс")).toBe("Стол Прованс");
  });

  it("не трогает похожие слова и чужие названия", () => {
    expect(strip("Диван прямой Викс")).toBe("Диван прямой Викс");
    expect(shopStripper(["divan.ru"])("Стул Divanboss АСТИ")).toBe("Стул Divanboss АСТИ");
    expect(strip("Стул АСТИ 2 шт. экокожа")).toBe("Стул АСТИ 2 шт. экокожа");
  });

  it("табуляция фида — в пробел; без магазинов и из одного магазина — название остаётся", () => {
    expect(strip("Денди кресло-кровать\tВелюр")).toBe("Денди кресло-кровать Велюр");
    expect(shopStripper([])("Диван divan.ru")).toBe("Диван divan.ru");
    expect(strip("divan.ru")).toBe("divan.ru");
  });
});
