# ------------------ Metin Temizleme / Rewrite (Gelişmiş) ------------------

import re
from unidecode import unidecode
from bs4 import BeautifulSoup

MAX_LEN = 240
SPACE_FIX = re.compile(r"\s+")
PUNCT_FIX = re.compile(r"\s+([,.!?;:])")
QUOTES = {'“':'"', '”':'"', '’':"'", '‘':"'", '«':'"', '»':'"'}

# Cümle sonunu olası “eksik” bitişlerden ayıklarken kullanacağımız kara liste
BAD_END_TOKENS = {"ve", "ile", "gibi", "ancak", "fakat", "ama", "çünkü", "veya", "ya da", "ya da.", "vb", "vb."}
BAD_END_CHARS = {",", ":", ";", "—", "–", "-", "…", "“", "‘", "'", '"'}

def normalize_quotes(s: str) -> str:
    for k,v in QUOTES.items():
        s = s.replace(k, v)
    return s

def clean_html_text(s: str) -> str:
    s = BeautifulSoup(s or "", "lxml").get_text(" ")
    s = normalize_quotes(s)
    s = SPACE_FIX.sub(" ", s).strip()
    s = PUNCT_FIX.sub(r"\1", s)
    return s

def ensure_period(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    return s if s[-1] in ".!?" else s + "."

def is_complete_sentence(s: str) -> bool:
    """Cümle tamam mı? (son karakter ve son kelimeye göre kaba kontrol)"""
    if not s: return False
    s = s.strip()
    if s[-1] in BAD_END_CHARS: return False
    last = s.rstrip(".!?").split()[-1].lower() if s.split() else ""
    if last in BAD_END_TOKENS: return False
    # çok kısa/tek kelime gibi şeyleri ele
    if len(s) < 20 and " " not in s: return False
    # başı büyük harf ya da sayı ile başlasın
    if not (s[0].isupper() or s[0].isdigit()): return False
    return True

def split_sentences_tr(s: str):
    # kısa kısım: ., !, ? ve “.” sonrası boşluğa göre böl
    parts = re.split(r"(?<=[.!?])\s+", s.strip())
    # sonu berbat bitiyorsa kes
    out = []
    for p in parts:
        p = p.strip()
        if not p: continue
        # uzun parça içinde URL/çöp varsa kırp
        p = re.sub(r"http\S+", "", p).strip()
        out.append(p)
    return out

def too_similar(a: str, b: str) -> bool:
    A = set(unidecode(a.lower()).split())
    B = set(unidecode(b.lower()).split())
    if not A or not B: return False
    inter = len(A & B) / max(1, len(A | B))
    return inter >= 0.6

def strip_site_trailer(title: str) -> str:
    # "Başlık | Site Adı" gibi son ekleri at
    return re.sub(r"\s*\|\s*[^|]+$", "", title).strip()

def pick_title_speaker(title: str):
    """
    'Kişi/Ünvan: cümle' kalıbını yakala → (speaker, quote)
    """
    if ":" not in title:
        return None
    left, right = title.split(":", 1)
    left = left.strip()
    right = right.strip().strip('"').strip("'")
    # 2–6 kelime arası özne, ilk harf büyük ise makul say
    if 2 <= len(left.split()) <= 6 and left[0].isupper():
        return left, right
    return None

def trim_to_limit(text: str, limit: int = MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    # kelime sınırında kırp
    cut = text[:limit-1].rsplit(" ", 1)[0].rstrip(",;:—–-")
    return (cut[:limit-1] + "…").rstrip()

def score_candidate(text: str) -> int:
    """
    Yüksek skor = daha iyi. Basit sezgisel puanlama:
    - tamamlanmış cümle bonusu
    - çok tekrar/çok tırnak/çok büyük harf cezası
    - uzunluk 120–240 arası ise bonus
    """
    t = text.strip()
    score = 0
    if is_complete_sentence(t): score += 5
    if 120 <= len(t) <= 240: score += 3
    if t.count('"') + t.count("'") > 4: score -= 2
    if len([w for w in t.split() if w.isupper() and len(w) > 2]) > 2: score -= 2
    return score

def rebuild_without_repeated_name(text: str, speaker: str) -> str:
    """
    Özet cümlesinde konuşmacı adı tekrar geçiyorsa temizle:
    'Cumhurbaşkanı Yardımcısı Cevdet Yılmaz ...' → 'Cumhurbaşkanı Yardımcısı ...'
    """
    # en basit: soyad/isim kombinasyonunu sil
    parts = speaker.split()
    if len(parts) >= 2:
        name = parts[-2] + " " + parts[-1]
        text = re.sub(re.escape(name), "", text, flags=re.I).strip()
        text = SPACE_FIX.sub(" ", text)
    return text

def rewrite_tr(title: str, summary: str) -> str:
    """
    Başlık + özetten 1–2 temiz cümle üretir.
    - 'Kişi: ...' kalıbı → 'Kişi: ... .' + (gerekirse) bir kısa ek cümle
    - tekrar ve yarım cümleler temizlenir
    - 240 karakter sınırı
    """
    t_raw = strip_site_trailer(clean_html_text(title))
    s_raw = clean_html_text(summary)

    # "SON DAKİKA" vs
    t_raw = re.sub(r"^\s*(SON DAK[Iİ]KA[:\-–]?)\s*", "", t_raw, flags=re.I)

    # 1) Speaker kalıbı
    sp = pick_title_speaker(t_raw)
    candidates = []
    if sp:
        speaker, quote = sp
        quote_sentences = split_sentences_tr(quote)
        quote_clean = quote_sentences[0] if quote_sentences else quote
        quote_clean = ensure_period(quote_clean)

        base = f"{speaker}: {quote_clean}"
        base = trim_to_limit(base)

        # Özetin ilk düzgün cümlesini ekleyelim (isim tekrarını azalt)
        add = ""
        if s_raw and not too_similar(base, s_raw):
            s1 = split_sentences_tr(s_raw)
            s1 = [x for x in s1 if is_complete_sentence(x)]
            if s1:
                s_try = rebuild_without_repeated_name(s1[0], speaker)
                if not too_similar(base, s_try):
                    add = " " + ensure_period(s_try)
        cand = trim_to_limit((base + add).strip())
        candidates.append(cand)

    # 2) Başlık cümlesi + özetten 1 kısa cümle
    title_first = split_sentences_tr(t_raw)
    if title_first:
        t1 = ensure_period(title_first[0])
        t1 = trim_to_limit(t1)
        add = ""
        if s_raw and not too_similar(t1, s_raw):
            s1 = split_sentences_tr(s_raw)
            s1 = [x for x in s1 if is_complete_sentence(x)]
            if s1 and not too_similar(t1, s1[0]):
                add = " " + ensure_period(s1[0])
        cand2 = trim_to_limit((t1 + add).strip())
        candidates.append(cand2)

    # 3) Sadece başlık (fallback)
    candidates.append(trim_to_limit(ensure_period(t_raw)))

    # En iyi aday
    best = max(candidates, key=score_candidate)
    return best
