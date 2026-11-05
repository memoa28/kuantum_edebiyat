import json, os, re, time
from pathlib import Path
from flask import Flask, Response, render_template, request, stream_with_context
from google import genai
from google.genai import types

BASE = Path(__file__).parent
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")  # çok istek gerekirse: bir Flash-Lite modeli
YEDEK = os.environ.get("GEMINI_YEDEK", "gemini-3.6-flash")
client = genai.Client(http_options=types.HttpOptions(timeout=180000))  # 3 dk (yavaş ama akan üretim yarıda kesilmesin); GEMINI_API_KEY ortam değişkeninden okunur
app = Flask(__name__)

REHBER = (BASE / "data/uslup_rehberi.md").read_text(encoding="utf-8")
CAPALAR = json.loads((BASE / "data/capalar.json").read_text(encoding="utf-8"))
CHUNKS = json.loads((BASE / "data/chunks.json").read_text(encoding="utf-8"))
SABIT = next(c["metin"] for c in CHUNKS if c["yuzde"] < 4 and "Aleksi" in c["metin"])  # kısa cümleli açılış: genel ses örneği
SADE = os.environ.get("SADE_MOD") == "1"  # 1: ölçülmüş sade üslup + sabit örnek + açık giriş sahnesi
if SADE:
    REHBER = REHBER.replace("## Çıktı kuralları", (BASE / "data/uslup_sade_ek.md").read_text(encoding="utf-8") + "## Çıktı kuralları")
ACILIS = json.loads((BASE / "data/acilis.json").read_text(encoding="utf-8"))  # kitabın gerçek açılışı (sabit)
ADIM_PER_CAPA = 3  # her çıpada 2 hazırlık kesiti + 1 gerçek dönüm noktası


def pasajlar(capa, k=3):
    """Çıpanın bölgesinden, anahtar sözcüğü ve diyaloğu en yoğun k parçayı seç."""
    lo, hi = capa["aralik"]
    aday = [c for c in CHUNKS if lo <= c["yuzde"] <= hi]
    puan = lambda c: 2 * sum(c["metin"].count(w) for w in capa["anahtar"]) + min(c["metin"].count(" -"), 3)
    return [c["metin"] for c in sorted(aday, key=puan, reverse=True)[:k]]


GIRIS = "\nBU KESİT YENİ BİR SAHNENİN GİRİŞİDİR: önce yeri, zamanı ve durumu 1-2 kısa cümleyle kur, sonra sahneye gir. Sahneyi ortasından başlatma; okuyucu neyin içinde olduğunu bilsin."


def ornek_listesi(capa):
    liste = pasajlar(capa)
    return [SABIT] + [x for x in liste if x != SABIT] if SADE else liste


def sistem_mesaji(capa, donum, ilk=False):
    ornek = "\n\n".join(f"[Örnek {i + 1}]\n{p}" for i, p in enumerate(ornek_listesi(capa)))
    gorev = (
        f"## ŞU ANKİ ÇIPA: {capa['ad']}\nKitaptaki olay: {capa['olay']}\n"
        + (f"BU KESİT GERÇEK BİR DÖNÜM NOKTASIDIR. Kesiti sahnenin en gergin anında bitir; seçenekler şu soruyu üç farklı yönde açsın: {capa['donum']}"
           if donum else "Bu kesit çıpaya doğru ilerleyen bir hazırlık kesitidir; seçenekler yine anlamlı ama küçük ölçekli olsun.")
    )
    if ilk and SADE:
        gorev += GIRIS
    return [
        {"type": "text", "text": REHBER, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"{gorev}\n\n## REŞAT NURİ'DEN ÖRNEK PASAJLAR (OCR'lı. YALNIZCA ritim ve söyleyiş içindir; cümleleri kopyalama, o sahneyi aynen tekrar etme)\n{ornek}"},
    ]


GECICI = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timed out", "Timeout", "timeout", "504", "DEADLINE_EXCEEDED")


def ayar(sistem, model):
    kw = dict(system_instruction=sistem, response_mime_type="application/json")
    if "3.8" in model:  # varsayılan 'medium' düşünme yavaş; düşük seviye yeterli
        kw["thinking_config"] = types.ThinkingConfig(thinking_level="low")
    return types.GenerateContentConfig(**kw)


def akis(istek, sistem):
    """Birincil modelden akışla üretir (2 deneme); olmazsa yedek modelden tek parça üretir."""
    for _ in range(2):
        toplam = ""
        try:
            for p in client.models.generate_content_stream(model=MODEL, contents=istek, config=ayar(sistem, MODEL)):
                if p.text:
                    toplam += p.text
                    yield toplam
            return
        except Exception as e:
            if not any(k in str(e) for k in GECICI):
                raise
            if toplam:
                yield None  # ekrandaki yarım metni sıfırla
            if any(k in str(e) for k in ("429", "504", "DEADLINE", "imed out")):
                break  # yavaş/limitli sunucuda aynı modeli tekrar denemek yerine yedeğe geç
            time.sleep(1)
    yield client.models.generate_content(model=YEDEK, contents=istek, config=ayar(sistem, YEDEK)).text


def hata_mesaji(e):
    t = str(e)
    if "429" in t or "RESOURCE_EXHAUSTED" in t:
        return "Ücretsiz limit doldu (dakikada 5 / günde ~20 istek). Biraz bekleyin."
    if "503" in t or "UNAVAILABLE" in t:
        return "Gemini şu an çok yoğun. “Tekrar dene”ye basın."
    if "imed out" in t or "imeout" in t or "504" in t or "DEADLINE" in t:
        return "Gemini zamanında yanıt vermedi (sunucu yavaş). “Tekrar dene”ye basın."
    return f"Üretim başarısız: {t}"


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/ilerle", methods=["POST"])
def ilerle():
    d = request.json or {}
    adim = int(d.get("adim", 0))
    ozetler, son_kesit, secim = d.get("ozetler", []), d.get("son_kesit", ""), d.get("secim")
    capa = CAPALAR[min(adim // ADIM_PER_CAPA, len(CAPALAR) - 1)]
    donum = adim % ADIM_PER_CAPA == ADIM_PER_CAPA - 1

    if adim == 0:  # ilk kesit modelden gelmez: kitabın gerçek açılışı anında verilir
        son = {**ACILIS, "capa": capa["ad"], "donum": False, "adim": 1}
        return Response(json.dumps({"son": son}, ensure_ascii=False) + "\n", mimetype="application/x-ndjson")
    if adim == 0:
        istek = (f"Hikâyeyi başlat. Başlangıç durumu: {capa['giris']} Birinci ağızdan, okuyucuyu bu duruma yerleştirerek baştan anlat."
                 if SADE else "Hikâyeyi başlat: Feride'nin ilk anısından, birinci ağızdan, ilk kesiti yaz.")
    else:
        istek = (f"Şimdiye kadarki evren (kronolojik): {' → '.join(ozetler)}\n\n"
                 f"Son yazdığın kesit:\n{son_kesit}\n\nOkuyucunun seçimi: {secim}\n\n"
                 "Hikâyeyi bu seçimden devam ettir ve yeni kesiti yaz.")
    sistem = "\n\n".join(b["text"] for b in sistem_mesaji(capa, donum, adim % ADIM_PER_CAPA == 0))

    def gen():
        son, gonderilen = "", 0
        try:
            for toplam in akis(istek, sistem):
                if toplam is None:
                    son, gonderilen = "", 0
                    yield json.dumps({"sifirla": 1}) + "\n"
                    continue
                son = toplam
                m = re.search(r'"kesit"\s*:\s*"((?:[^"\\]|\\.)*)', toplam)
                if not m:
                    continue
                try:
                    k = json.loads('"' + m.group(1) + '"')
                except Exception:
                    continue
                if len(k) > gonderilen:
                    yield json.dumps({"t": k[gonderilen:]}, ensure_ascii=False) + "\n"
                    gonderilen = len(k)
            veri = json.loads(re.search(r"\{.*\}", son, re.S).group(0))
            assert len(veri["secenekler"]) == 3 and veri["kesit"]
            yield json.dumps({"son": {**veri, "capa": capa["ad"], "donum": donum, "adim": adim + 1}}, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"hata": hata_mesaji(e)}, ensure_ascii=False) + "\n"

    return Response(stream_with_context(gen()), mimetype="application/x-ndjson")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
