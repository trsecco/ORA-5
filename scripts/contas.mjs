#!/usr/bin/env node
// Contas de luz criptografadas (contas.enc.json) para o app ORA 5.
// Uso:
//   node scripts/contas.mjs list  SENHA            -> mostra os meses já gravados
//   node scripts/contas.mjs add   SENHA '<json>'   -> acrescenta uma conta (objeto JSON) e recriptografa
//   node scripts/contas.mjs show  SENHA            -> mostra tudo descriptografado (só para conferência local)
// Formato: AES-256-GCM, chave derivada da senha por PBKDF2-SHA256 (310.000 iterações).
// O app (index.html) descriptografa com a mesma senha, guardada só no iPhone.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const { subtle } = globalThis.crypto;

const ARQ = join(dirname(fileURLToPath(import.meta.url)), "..", "contas.enc.json");
const ITER = 310000;
const b64 = (u) => Buffer.from(u).toString("base64");
const ub64 = (s) => new Uint8Array(Buffer.from(s, "base64"));

async function chave(senha, salt) {
  const base = await subtle.importKey("raw", new TextEncoder().encode(senha.trim()), "PBKDF2", false, ["deriveKey"]);
  return subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations: ITER }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
async function ler(senha) {
  if (!existsSync(ARQ)) return { contas: [] };
  const e = JSON.parse(readFileSync(ARQ, "utf8"));
  const k = await chave(senha, ub64(e.salt));
  let txt;
  try { txt = new TextDecoder().decode(await subtle.decrypt({ name: "AES-GCM", iv: ub64(e.iv) }, k, ub64(e.data))); }
  catch { throw new Error("Senha incorreta ou arquivo corrompido — nada foi alterado."); }
  return JSON.parse(txt);
}
async function gravar(senha, obj) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const k = await chave(senha, salt);
  const data = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv }, k, new TextEncoder().encode(JSON.stringify(obj))));
  const hoje = new Date().toISOString().slice(0, 10);
  writeFileSync(ARQ, JSON.stringify({ v: 1, alg: "AES-256-GCM", kdf: "PBKDF2-SHA256", iter: ITER, salt: b64(salt), iv: b64(iv), data: b64(data), atualizado: hoje }) + "\n");
}
function valida(c) {
  const d = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "");
  if (!/^\d{4}-\d{2}$/.test(c.ref || "")) throw new Error("ref inválido (AAAA-MM)");
  if (!d(c.de) || !d(c.ate) || c.ate <= c.de) throw new Error("datas de/ate inválidas");
  const dias = (Date.parse(c.ate) - Date.parse(c.de)) / 864e5;
  if (dias < 25 || dias > 40) throw new Error("período fora de 25–40 dias");
  if (!(c.kwh >= 30 && c.kwh <= 3000)) throw new Error("kwh fora de 30–3000");
  if (!(c.energia > 0)) throw new Error("energia inválida");
  c.tarifa = Math.round((c.energia / c.kwh) * 10000) / 10000;
  if (!(c.tarifa >= 0.5 && c.tarifa <= 2.5)) throw new Error("tarifa fora de 0,50–2,50");
  return c;
}

const [cmd, senha, arg] = process.argv.slice(2);
if (!cmd || !senha) { console.error("uso: node scripts/contas.mjs list|add|show SENHA ['<json>']"); process.exit(2); }
try {
  const d = await ler(senha);
  d.contas = d.contas || [];
  if (cmd === "list") console.log(d.contas.map((c) => c.ref).join(" ") || "(nenhuma)");
  else if (cmd === "show") console.log(JSON.stringify(d, null, 1));
  else if (cmd === "add") {
    const c = valida(JSON.parse(arg));
    if (d.contas.some((x) => x.ref === c.ref)) { console.log("já existe: " + c.ref + " (nada alterado)"); process.exit(0); }
    d.contas.push(c); d.contas.sort((a, b) => (a.ref < b.ref ? -1 : 1));
    d.atualizado = new Date().toISOString().slice(0, 10);
    await gravar(senha, d);
    console.log("gravada: " + c.ref + " · " + c.kwh + " kWh · R$ " + c.tarifa.toFixed(4) + "/kWh");
  } else throw new Error("comando desconhecido: " + cmd);
} catch (e) { console.error("ERRO: " + e.message); process.exit(1); }
