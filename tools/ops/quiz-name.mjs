// ИМЯ ДЛЯ ПРИВЕТСТВИЯ ОПРОСА (onb-03 Т2, ADR-0330 п.4). Менеджер добавляет к ссылке `#n=<имя>`; страница читает его первым
// скриптом в <head>, сразу стирает из адреса (`history.replaceState`) и держит только в sessionStorage — так имя не попадёт
// в «поделиться», WhatsApp-текст и строку адреса на JPG. Чистая функция — блок QUIZNAME; onb-03 переносит его в `index.html`
// дословно (как QUIZPICK), тест `tests/unit/quiz-name.test.ts` меняет тогда только SRC. Строитель ссылки у менеджера — `lib/quiz/name.ts`.

// QUIZNAME START
/* Имя: 1–30 символов, только буквы (любой азбуки), пробел и дефис, хотя бы одна буква; иначе отброс целиком (цифры — телефон). */
function quizCleanName(s){
  const n=String(s==null?'':s).normalize('NFC').replace(/\s+/g,' ').trim();
  return n.length<=30&&/^[\p{L}\- ]+$/u.test(n)&&/\p{L}/u.test(n)?n:'';
}
/* `#n=Анна`, `#v=x&n=Анна`, `#n=Анна&v=x` → имя и адрес без `n=` (остальной фрагмент — как был). `n=` стирается всегда,
   даже негодное. Битое %-кодирование — отброс. */
function nameFromHash(hash){
  const body=String(hash||'').replace(/^#/,'');
  if(!body)return {name:'',hash:''};
  let name='',seen=false;
  const rest=body.split('&').filter(p=>{
    if(p.slice(0,2)!=='n=')return true;
    if(!seen){seen=true; try{name=quizCleanName(decodeURIComponent(p.slice(2).replace(/\+/g,' ')));}catch(e){name='';}}
    return false;
  });
  return {name, hash: seen?(rest.length?'#'+rest.join('&'):''):String(hash||'')};
}
// QUIZNAME END

export { nameFromHash, quizCleanName };
