#!/usr/bin/env python3
"""Leitor da fatura da CEEE Equatorial (referência para o importador do app). Não roda automaticamente.

Uso:
  python scripts/ceee.py                 # busca no Gmail (precisa de GMAIL_USER e GMAIL_APP_PASSWORD)
  python scripts/ceee.py --pdf fatura.pdf  # só testa a leitura de um PDF local
"""
import imaplib, email, json, os, re, subprocess, sys, tempfile, datetime as dt
from email.header import decode_header

ARQ = os.path.join(os.path.dirname(__file__), "..", "contas.json")

def num(s):  # "1.234,56" -> 1234.56
    return float(s.replace(".", "").replace(",", "."))

def pdf_texto(caminho):
    return subprocess.run(["pdftotext", "-layout", caminho, "-"], capture_output=True, text=True, check=True).stdout

def iso(d):  # dd/mm/aaaa -> aaaa-mm-dd
    return f"{d[6:10]}-{d[3:5]}-{d[0:2]}"

def ler_fatura(txt):
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{1,3})\s+\d{2}/\d{2}/\d{4}", txt)
    if not m: raise ValueError("datas de leitura não encontradas")
    de, ate = iso(m.group(1)), iso(m.group(2))
    r = re.search(r"^\s*(\d{2})/(\d{4})\s+\d{2}/\d{2}/\d{4}\s+R\$\s*([\d.]+,\d{2})", txt, re.M)
    if not r: raise ValueError("mês de referência / total não encontrado")
    ref, total = f"{r.group(2)}-{r.group(1)}", num(r.group(3))
    energia, kwh = 0.0, None
    for linha in txt.splitlines():
        l = linha.strip()
        nums = re.findall(r"\d[\d.]*,\d+|\b\d+\b", l)
        if re.match(r"Consumo\s+(TE|TU|TUSD)\b", l, re.I) and len(nums) >= 3:
            q, t = num(nums[0]) if "," in nums[0] else float(nums[0]), num(nums[1])
            cand = [num(x) for x in nums[2:5] if "," in x]
            v = min(cand, key=lambda x: abs(x - q * t))  # valor = quantidade × tarifa
            energia += v
            if kwh is None: kwh = q
        elif re.match(r"(Adicional\s+Bandeira|Adic\.?\s*Band)", l, re.I):
            money = [x for x in nums if "," in x]
            if money: energia += num(money[0])
    if not kwh: raise ValueError("consumo em kWh não encontrado")
    tarifa = round(energia / kwh, 4)
    dias = (dt.date.fromisoformat(ate) - dt.date.fromisoformat(de)).days
    if not (25 <= dias <= 40): raise ValueError(f"período estranho: {dias} dias")
    if not (30 <= kwh <= 3000): raise ValueError(f"consumo estranho: {kwh} kWh")
    if not (0.5 <= tarifa <= 2.5): raise ValueError(f"tarifa estranha: {tarifa}")
    return {"ref": ref, "de": de, "ate": ate, "kwh": int(kwh) if kwh == int(kwh) else kwh,
            "energia": round(energia, 2), "tarifa": tarifa, "total": total,
            "fonte": f"CEEE Equatorial – fatura {ref[5:]}/{ref[:4]}"}

def pdfs_do_gmail(user, senha, dias=45):
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(user, senha)
    pasta = "INBOX"  # procura a pasta "Todos os e-mails" (atributo \\All), qualquer que seja o idioma
    typ, lst = M.list()
    for l in lst or []:
        l = l.decode(errors="ignore")
        if "\\All" in l:
            pasta = l.split(' "/" ')[-1]; break
    M.select(pasta, readonly=True)
    desde = (dt.date.today() - dt.timedelta(days=dias)).strftime("%d-%b-%Y")
    ids = set()
    for crit in ('(FROM "ContaPorEmail@ceee.com.br")', '(SUBJECT "Fatura CEEE")', '(BODY "ContaPorEmail@ceee.com.br")'):
        typ, data = M.search(None, f'(SINCE {desde})', crit)
        if typ == "OK": ids.update(data[0].split())
    for i in sorted(ids):
        typ, data = M.fetch(i, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        for part in msg.walk():
            nome = part.get_filename()
            if nome:
                nome = "".join(t.decode(c or "utf-8") if isinstance(t, bytes) else t for t, c in decode_header(nome))
            if (part.get_content_type() == "application/pdf" or (nome or "").lower().endswith(".pdf")) and part.get_payload(decode=True):
                yield nome or "fatura.pdf", part.get_payload(decode=True)
    M.logout()

def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--pdf":
        print(json.dumps(ler_fatura(pdf_texto(sys.argv[2])), ensure_ascii=False)); return
    user, senha = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not senha: sys.exit("Faltam os segredos GMAIL_USER e GMAIL_APP_PASSWORD")
    dados = json.load(open(ARQ, encoding="utf-8")) if os.path.exists(ARQ) else {"contas": []}
    refs = {c["ref"] for c in dados.get("contas", [])}
    novas = []
    for nome, conteudo in pdfs_do_gmail(user, senha):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(conteudo); f.flush()
            try:
                c = ler_fatura(pdf_texto(f.name))
            except Exception as e:
                print(f"⚠️ {nome}: não li ({e})"); continue
        if c["ref"] in refs: print(f"= {nome}: conta {c['ref']} já existe"); continue
        refs.add(c["ref"]); novas.append(c); print(f"+ {nome}: {c}")
    if novas:
        dados["contas"] = sorted(dados.get("contas", []) + novas, key=lambda c: c["ref"])
        dados["atualizado"] = dt.date.today().isoformat()
        json.dump(dados, open(ARQ, "w", encoding="utf-8"), ensure_ascii=False)
        open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a").write("msg=Conta de luz CEEE " + ", ".join(f"{c['ref']}: R$ {str(c['tarifa']).replace('.', ',')}/kWh" for c in novas) + "\n")
    else:
        print("sem conta nova")

if __name__ == "__main__":
    main()
