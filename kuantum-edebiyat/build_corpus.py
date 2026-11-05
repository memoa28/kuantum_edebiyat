"""Çalıkuşu PDF'ini temizleyip data/chunks.json üretir. Gerekli: poppler (pdftotext)."""
import json, re, subprocess, sys
pdf = sys.argv[1]
t = subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout
t = re.sub(r"www\.CepSitesi\.Net|Resat Nuri Güntekin - Çalıkuşu|ÇALIKUSU \d+|Resat Nuri Güntekin|\f", " ", t)
t = re.sub(r"(?<=\S)\n(?=\S)", " ", t)
t = re.sub(r"[ \t]+", " ", t)
paras = [p.strip() for p in re.split(r"\n\s*\n+", t) if len(p.strip()) > 40]
chunks, buf, pos = [], "", 0
for p in paras:
    buf += (" " if buf else "") + p
    if len(buf) >= 500:
        chunks.append({"yuzde": round(pos * 100 / len(t), 1), "metin": buf[:900]})
        buf = ""
    pos += len(p) + 2
json.dump(chunks, open("data/chunks.json", "w", encoding="utf-8"), ensure_ascii=False)
print(len(chunks), "parça")
