// ПОДПИСЬ ФАЙЛА ДАМПЕРА (T-20261118-10/5 ❶): отметка обращения (`utime`) подпись не меняет; новый файл того же размера (замена меша) — меняет; правка в середине файла, которой не видно
// ни голове, ни хвосту, при том же размере и inode не замечается (так задумано: меш заменяют целиком — новым файлом). Запуск: node tools/scout/cycles_probe/test_file_sig.mjs
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileSig, SIG_EDGE } from './file_sig.mjs';

const fails = [];
const check = (name, ok) => { console.log((ok ? 'OK   ' : 'FAIL ') + name); if (!ok) fails.push(name); };
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'filesig-'));
const rnd = (n, seed) => { const b = Buffer.alloc(n); let x = seed; for (let i = 0; i < n; i++) { x = (x * 1103515245 + 12345) & 0x7fffffff; b[i] = x >> 16; } return b; };

const big = path.join(dir, 'big.glb');
fs.writeFileSync(big, rnd(5 * SIG_EDGE, 1));
const s0 = fileSig(big);
check('подпись стабильна при повторном чтении', fileSig(big) === s0);

const t = new Date(Date.now() + 3600_000);
fs.utimesSync(big, t, t);                       // как `draft_render._touch`: время изменилось, содержимое нет
check('utime (отметка обращения) подпись НЕ меняет', fileSig(big) === s0);

const other = path.join(dir, 'other.glb');      // замена меша: новый файл того же размера, другое содержимое
fs.writeFileSync(other, rnd(5 * SIG_EDGE, 2));
check('новый файл того же размера, другое содержимое — подпись другая', fileSig(other) !== s0);

fs.renameSync(other, big);                      // подменили файл под тем же именем (новый inode, тот же размер)
check('замена файла под тем же именем (rename) — подпись другая', fileSig(big) !== s0);

const small = path.join(dir, 'small.glb');
fs.writeFileSync(small, rnd(1000, 3));
const a = fileSig(small);
fs.writeFileSync(small, rnd(1000, 4));          // файл меньше 64 КБ: голова = весь файл
check('малый файл: правка содержимого того же размера замечается', fileSig(small) !== a);

fs.writeFileSync(small, rnd(70000, 5));         // между 64 и 128 КБ: хвост не пересекается с головой за пределами файла
const b = fileSig(small);
fs.writeFileSync(small, Buffer.concat([rnd(69000, 5), rnd(1000, 6)]));
check('файл 64–128 КБ: правка в хвосте замечается', fileSig(small) !== b);

fs.rmSync(dir, { recursive: true, force: true });
console.log('итог:', fails.length ? `${fails.length} падений` : 'чисто');
process.exit(fails.length ? 1 : 0);
