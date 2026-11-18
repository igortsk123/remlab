// ПОДПИСЬ ФАЙЛА для кэшей страницы дампера (разобранные меши, закодированные картинки GLB): размер + inode + md5 головы и хвоста (по 64 КБ).
// Время изменения в подпись НЕ входит: кэш мешей на DEV отмечает каждое обращение `utime` (`draft_render._touch`), и «размер-время» объявляло файл заменённым в каждом
// заказе — разбор всех мешей заново (T-20261118-10/4; тот же корень и то же правило, что `export_server.file_sig`). Тест — `test_file_sig.mjs`.
import fs from 'fs';
import crypto from 'crypto';

export const SIG_EDGE = 65536;

export function fileSig(f) {
  const st = fs.statSync(f), fd = fs.openSync(f, 'r');
  try {
    const h = crypto.createHash('md5'), b = Buffer.alloc(Math.min(SIG_EDGE, st.size));
    fs.readSync(fd, b, 0, b.length, 0); h.update(b);
    if (st.size > SIG_EDGE) { const t = Buffer.alloc(Math.min(SIG_EDGE, st.size - SIG_EDGE)); fs.readSync(fd, t, 0, t.length, st.size - t.length); h.update(t); }
    return `${st.size}-${st.ino}-${h.digest('hex').slice(0, 16)}`;
  } finally { fs.closeSync(fd); }
}
