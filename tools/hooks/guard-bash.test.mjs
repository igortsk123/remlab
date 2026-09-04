#!/usr/bin/env node
// Тест гарда `guard-bash.mjs`. Запуск: node tools/hooks/guard-bash.test.mjs
// Случаи держим в ФАЙЛЕ, а не в командной строке: иначе гард заблокирует сам запуск теста.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const GUARD = join(dirname(fileURLToPath(import.meta.url)), 'guard-bash.mjs');

const BLOCK = 'pkill' + ' -f';
const GREP = 'pgrep' + ' -f';

const cases = [
  // [команда, ожидаемый код: 2 = заблокировать, 0 = пропустить]
  [`${BLOCK} batch_show`, 2],
  [`${GREP} ssh_run`, 2],
  [`sudo pkill -9 -f salad`, 2],
  [`cd /tmp && ${BLOCK} worker`, 2],
  [`pgrep -af ssh_run`, 2],
  ['ls -la', 0],
  ['ps -eo pid,comm,args | grep salad', 0],
  ['kill 12345', 0],
  ['pkill batch_show', 0], // без -f: матч по имени процесса, обёртку не задевает
  ['git commit -m "fix"', 0],
  // НЕ выполняется — только текст. Гард ловил сам себя на коммите про эту же граблю (04.09).
  [`git commit -F - <<'MSG'\nгард блокирует ${BLOCK} и ${GREP}\nMSG`, 0],
  [`echo "как не надо: ${BLOCK} worker"`, 0],
  [`echo 'и ${GREP} тоже'`, 0],
];

let bad = 0;
for (const [cmd, want] of cases) {
  const r = spawnSync('node', [GUARD], {
    input: JSON.stringify({ tool_input: { command: cmd } }),
    encoding: 'utf8',
  });
  const got = r.status;
  const ok = got === want;
  if (!ok) bad++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  exit=${got} (ждали ${want})  ${cmd}`);
}

// Fail-open: мусор на входе не должен блокировать Bash.
const junk = spawnSync('node', [GUARD], { input: 'не json', encoding: 'utf8' });
const junkOk = junk.status === 0;
if (!junkOk) bad++;
console.log(`${junkOk ? 'ok  ' : 'FAIL'}  exit=${junk.status} (ждали 0)  <мусор на stdin — fail-open>`);

console.log(bad === 0 ? '\nВСЁ ЗЕЛЁНОЕ' : `\nПРОВАЛЕНО: ${bad}`);
process.exit(bad === 0 ? 0 : 1);
