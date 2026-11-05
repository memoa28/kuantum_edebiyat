"""Hangi model sende en hızlı? Kullanım:
   python hiz_testi.py --liste                  (anahtarınızın görebildiği flash modellerini listeler)
   python hiz_testi.py gemini-3.8-flash gemini-3.6-flash   (verilen modellerin süresini ölçer)"""
import sys, time
from google import genai
from google.genai import types

client = genai.Client(http_options=types.HttpOptions(timeout=120000))
if sys.argv[1:] == ["--liste"]:
    for m in client.models.list():
        if "flash" in m.name or "gemma" in m.name:
            print(m.name.replace("models/", ""))
    sys.exit()
for m in sys.argv[1:] or ["gemini-3.8-flash", "gemini-3.6-flash"]:
    t = time.time()
    try:
        cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low")) if "3.8" in m else None
        r = client.models.generate_content(model=m, config=cfg,
            contents="Reşat Nuri üslubuyla, birinci ağızdan iki paragraf yaz: mektep yolunda gördüğüm sonbahar.")
        print(f"{m}: {time.time() - t:.1f} sn, {len(r.text)} karakter")
    except Exception as e:
        print(f"{m}: HATA ({time.time() - t:.1f} sn) -> {str(e)[:120]}")
