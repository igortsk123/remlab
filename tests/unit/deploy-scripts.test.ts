import { readdirSync, readFileSync } from "node:fs";
import { basename } from "node:path";
import { describe, expect, it } from "vitest";

// СКРИПТЫ ТАЙМЕРОВ ЕДУТ НА СЕРВЕР С ВЫКЛАДКОЙ (T-20261020-02). Таймер systemd запускает файл из
// /opt/remlab/scripts/, а туда его кладёт только выкладка (`deploy.yml` и ручной `deploy.sh`). Забытый
// в списке скрипт молча работает по старой серверной версии — так было с ночной копией базы db-backup.sh.
const UNITS = "infra/server/systemd";
const execScripts = readdirSync(UNITS)
  .filter((f) => f.endsWith(".service"))
  .flatMap((f) => [...readFileSync(`${UNITS}/${f}`, "utf8").matchAll(/^ExecStart=.*?\/opt\/remlab\/scripts\/(\S+)/gm)])
  .map((m) => m[1]);

// Строка копирования: `scp <файлы репо> "<сервер>:<каталог>/scripts/"`; строка прав: `chmod +x <пути на сервере>`.
function deployLists(path: string) {
  const text = readFileSync(path, "utf8");
  const scp = text.split("\n").find((l) => /^\s*scp .*\/scripts\/"\s*$/.test(l));
  const chmod = text.split("\n").find((l) => /ssh .*"chmod \+x .*\/scripts\//.test(l));
  return {
    copied: (scp ?? "").trim().split(/\s+/).slice(1, -1),
    executable: [...(chmod ?? "").matchAll(/\/scripts\/([^\s"]+)/g)].map((m) => m[1]),
  };
}

describe("выкладка возит скрипты, которые запускают таймеры сервера", () => {
  it("таймеры найдены (среди них ночная копия базы)", () => {
    expect(execScripts).toContain("db-backup.sh");
  });

  for (const path of ["deploy.sh", ".github/workflows/deploy.yml"]) {
    describe(path, () => {
      const { copied, executable } = deployLists(path);
      for (const script of execScripts) {
        it(`${script}: копируется из репо и получает право на запуск`, () => {
          const src = copied.find((f) => basename(f) === script);
          expect(src, `нет в строке scp ${path}`).toBeDefined();
          expect(() => readFileSync(src!)).not.toThrow();
          expect(executable, `нет в chmod +x ${path}`).toContain(script);
        });
      }
    });
  }
});
