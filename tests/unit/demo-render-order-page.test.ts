// T-20261118-20/5: страница шлёт заказ рендера «Сделать фото» так, чтобы комната БЕЗ правок давала тот же хеш, что заготовка кадров («как есть»):
// координаты — до десятых (сервер округляет до 0,1 см; целые сантиметры сдвигали место и хеш), ключ предмета — один из sid / pid / ref (контракт `contracts/trial.ts`),
// никаких догадок по имени (`msid`+`name`). Живая проверка хеша на данных витрины — `tools/ops/demo-walk/*`, здесь — закрепление кода заказа.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const start = html.indexOf("function vwRenderReq()");
const body = html.slice(start, html.indexOf("\n}\n", start));

describe("заказ рендера со страницы (vwRenderReq)", () => {
  it("координаты до десятых, не целые", () => {
    expect(body).toMatch(/x:r1\(it\.x\), y:r1\(it\.y\)/);
    expect(body).not.toMatch(/x:Math\.round\(\+it\.x/);
  });
  it("ключ предмета: sid, иначе pid, иначе ref; догадки по имени нет", () => {
    expect(body).toMatch(/\{sid:String\(k\.sid\)\}/);
    expect(body).toMatch(/\{pid:k\.pid\}/);
    expect(body).toMatch(/\{ref:r\}/);
    expect(body).not.toMatch(/msid/);
    expect(body).not.toMatch(/name:String\(k\.name\)/);
  });
  it("статус машины от сервера читается из ответа (machine.state = warming)", () => {
    expect(html).toMatch(/job\.mach=\(v\.machine&&typeof v\.machine==='object'\)\?v\.machine:null/);
    expect(html).toMatch(/mc&&mc\.state==='warming'/);
  });
});
