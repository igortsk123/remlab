// Проверка распаковщика из Фигмы на частях «Шторки»: какая часть ломает его и где.
const fs = require('fs');
const zlib = require('zlib');
const atob = (s) => Buffer.from(s, 'base64').toString('binary');
function inflateB64(b64) {
  const bin = atob(b64); const src = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) src[i] = bin.charCodeAt(i);
  let pos = 2, bit = 0, bits = 0; const out = [];
  const need = (n) => { while (bits < n) { bit |= src[pos++] << bits; bits += 8; } };
  const get = (n) => { need(n); const v = bit & ((1 << n) - 1); bit >>>= n; bits -= n; return v; };
  function table(lens) {
    const count = new Uint16Array(16), offs = new Uint16Array(16), sym = new Uint16Array(lens.length);
    for (const l of lens) count[l]++;
    count[0] = 0;
    for (let i = 1; i < 16; i++) offs[i] = offs[i - 1] + count[i - 1];
    for (let i = 0; i < lens.length; i++) if (lens[i]) sym[offs[lens[i]]++] = i;
    return { count, sym };
  }
  function decode(t) {
    let code = 0, first = 0, index = 0;
    for (let len = 1; len < 16; len++) {
      code |= get(1); const c = t.count[len];
      if (code - first < c) return t.sym[index + code - first];
      index += c; first += c; first <<= 1; code <<= 1;
    }
    throw new Error('bad code');
  }
  const LB = [3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258];
  const LE = [0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0];
  const DB = [1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577];
  const DE = [0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13];
  let fixedL, fixedD;
  function fixed() {
    if (!fixedL) {
      const l = []; for (let i = 0; i < 288; i++) l.push(i < 144 ? 8 : i < 256 ? 9 : i < 280 ? 7 : 8);
      fixedL = table(l); fixedD = table(new Array(30).fill(5));
    }
    return [fixedL, fixedD];
  }
  function dynamic() {
    const hl = get(5) + 257, hd = get(5) + 1, hc = get(4) + 4;
    const ord = [16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15];
    const cl = new Array(19).fill(0);
    for (let i = 0; i < hc; i++) cl[ord[i]] = get(3);
    const ct = table(cl); const lens = [];
    while (lens.length < hl + hd) {
      const s = decode(ct);
      if (s < 16) lens.push(s);
      else if (s === 16) { const p = lens[lens.length - 1]; for (let r = 3 + get(2); r > 0; r--) lens.push(p); }
      else if (s === 17) { for (let r = 3 + get(3); r > 0; r--) lens.push(0); }
      else { for (let r = 11 + get(7); r > 0; r--) lens.push(0); }
    }
    return [table(lens.slice(0, hl)), table(lens.slice(hl))];
  }
  let last = 0, blocks = [];
  while (!last) {
    last = get(1); const type = get(2); blocks.push(type);
    if (type === 0) {
      bit = 0; bits = 0; const len = src[pos] | (src[pos + 1] << 8); pos += 4;
      for (let i = 0; i < len; i++) out.push(src[pos++]);
      continue;
    }
    const [lt, dt] = type === 1 ? fixed() : dynamic();
    for (;;) {
      let s = decode(lt);
      if (s < 256) { out.push(s); continue; }
      if (s === 256) break;
      s -= 257; const len = LB[s] + get(LE[s]);
      const ds = decode(dt); const dist = DB[ds] + get(DE[ds]);
      for (let i = 0, from = out.length - dist; i < len; i++) out.push(out[from + i]);
      if (out.length > 200000) throw new Error('runaway at pos ' + pos + ' blocks ' + blocks + ' s=' + s + ' len=' + len + ' ds=' + ds);
    }
  }
  return { n: out.length, blocks };
}
for (const f of process.argv.slice(2)) {
  const b = fs.readFileSync(f, 'utf8').trim();
  const ref = zlib.inflateSync(Buffer.from(b, 'base64')).length;
  try { const r = inflateB64(b); console.log(f, 'ok', r.n, 'ref', ref, 'blocks', r.blocks.join(',')); }
  catch (e) { console.log(f, 'FAIL', e.message, 'ref', ref); }
}
