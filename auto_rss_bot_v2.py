#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_rss_bot_v3 — Genel amaçlı, kural-tabanlı Türkçe haber metni düzeltici + özetleyici.

Hedef:
- Tahmine dayalı bilgi KATMADAN (hallüsinasyon yok),
- Doğrudan alıntıları tırnak içine alma,
- Kurum kısaltmalarında (ABD, BM, AB, NATO, TBMM, TÜİK, vs.) eklerin apostrofla yazımı,
- Cümleleri konuya göre (varlık/özel ad) gruplama ve 1–3 kısa özet üretme,
- Basit yazım/boşluk/çıktı temizliği,
- “Başkanı <İsim>” gibi yapılarda, AYNI cümlede açık kurum kısaltması VARKEN güvenli unvan tamamlama (yoksa dokunma).

Agresif değil; emin olmadığında el sürmez.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Optional

# ———————————————————————————————————————
# Regex ve sabitler
# ———————————————————————————————————————
RE_WHITESPACE = re.compile(r"\s+")
RE_SENTENCE_SPLIT = re.compile(r"(?<=[\.\?\!])\s+")
SAY_VERBS = [
    "dedi", "açıkladı", "belirtti", "ifade etti", "konuştu",
    "söyledi", "ekledi", "vurguladı", "yanıtladı", "aktardı"
]
SAY_VERBS_RE = re.compile(rf"\b({'|'.join(map(re.escape, SAY_VERBS))})\b", re.IGNORECASE)

# Kurum kısaltmaları (apostrof + ek alır)
SAFE_ACRONYMS = {
    "ABD","BM","AB","NATO","TBMM","TÜİK","YÖK","IMF","UN","UNESCO","G20","OECD","ECB","FED",
    "WHO","UNHCR","UEFA","FIFA","NATO","ASEAN","G7","G8","G77","OPEC","BRICS"
}
# Türkçe eklerin güvenli altkümesi
SUFFIXES = [
    "den","dan","de","da","ye","ya","nin","nın","nun","nün",
    "ne","na","yla","yle","yi","yı","yu","yü","e","a"
]
ACRONYM_EK_RE = re.compile(rf"\b([A-ZÇĞİÖŞÜ]{2,})\s+((?:{'|'.join(SUFFIXES)}))\b")

@dataclass
class Summary:
    text: str
    topic: Optional[str] = None

@dataclass
class ProcessResult:
    summaries: List[Summary]
    cleaned_text: str

# ———————————————————————————————————————
# Temizlik
# ———————————————————————————————————————
def normalize_spaces(text: str) -> str:
    return RE_WHITESPACE.sub(" ", text).strip()

def common_soft_fixes(text: str) -> str:
    # Akıllı tırnakları normalize et
    text = text.replace("“", '"').replace("”", '"')
    # Noktadan önceki boşlukları temizle: "kelime ." -> "kelime."
    text = re.sub(r"\s+\.", ".", text)
    return text

# ———————————————————————————————————————
# Apostrof düzeltmeleri (yalnızca KISALTMA güvenli kümesinde)
# ———————————————————————————————————————
def fix_apostrophes_for_acronyms(text: str) -> str:
    def repl(m: re.Match) -> str:
        ac = m.group(1)
        ek = m.group(2)
        if ac.upper() in SAFE_ACRONYMS:
            return f"{ac}'{ek}"
        return m.group(0)
    return ACRONYM_EK_RE.sub(repl, text)

# ———————————————————————————————————————
# Güvenli unvan tamamlama
# “... ABD ... Başkanı <İsim> ...” deseninde, aynı cümlede ÖNCE kurum varsa:
#  -> “ABD Başkanı <İsim>”
# Önce kurum yoksa DOKUNMA (tahmin yok).
# ———————————————————————————————————————
def complete_missing_titles(text: str) -> str:
    def fix_sentence(sent: str) -> str:
        if "Başkanı " not in sent:
            return sent
        # "Başkanı <İsim>" ile böl
        parts = sent.split("Başkanı ", 1)
        before, after = parts[0], parts[1]
        found = None
        for ac in SAFE_ACRONYMS:
            if re.search(rf"\b{re.escape(ac)}\b", before):
                found = ac
        if not found:
            return sent  # emin değilsek bırak
        # Zaten “<AC> Başkanı” içeriyorsa bırak
        if re.search(rf"{re.escape(found)}\s+Başkanı", sent):
            return sent
        return before + f"{found} Başkanı " + after
    sents = RE_SENTENCE_SPLIT.split(text)
    sents = [s.strip() for s in sents if s.strip()]
    return " ".join(fix_sentence(s) for s in sents)

# ———————————————————————————————————————
# Doğrudan alıntıyı tırnak içine alma (temkinli)
# ———————————————————————————————————————
def insert_missing_quotes(text: str) -> str:
    def quote_in_sentence(sent: str) -> str:
        m = re.search(rf"(.+?)\s+({'|'.join(map(re.escape, SAY_VERBS))})(?=[\s\.,;:!?])", sent, re.IGNORECASE)
        if not m:
            return sent
        said = m.group(1).strip()
        # Zaten tırnak varsa veya aşırı uzunsa dokunma
        if '"' in said or len(said) > 220:
            return sent
        start, end = m.start(1), m.end(1)
        new = sent[:start] + '"' + said.rstrip(' .!?,;:') + '."' + sent[end:]
        return new
    sents = RE_SENTENCE_SPLIT.split(text)
    sents = [s.strip() for s in sents if s.strip()]
    return " ".join(quote_in_sentence(s) for s in sents)

# ———————————————————————————————————————
# Konu/varlık bazlı bölme (genel)
# - Cümlelerdeki Özel Ad + Kısaltma varlıklarını çıkar.
# - Benzer varlıklar içeren cümleleri aynı kovaya koy.
# - En büyük 1–3 kovayı özetle.
# ———————————————————————————————————————
TOKEN_ENT_RE = re.compile(r"[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|[A-ZÇĞİÖŞÜ]{2,}")

def sentence_entities(s: str) -> set:
    toks = TOKEN_ENT_RE.findall(s)
    ents = set(toks)
    # Kısaltmaları netleştir
    for t in list(ents):
        if t.upper() in SAFE_ACRONYMS:
            ents.add(t.upper())
    return ents

def split_into_topics(text: str, max_groups: int = 3) -> List[str]:
    sentences = RE_SENTENCE_SPLIT.split(text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return []
    buckets: Dict[str, List[str]] = {}
    for sent in sentences:
        ents = sentence_entities(sent)
        key = ",".join(sorted(ents)) if ents else "_genel_"
        buckets.setdefault(key, []).append(sent)
    groups = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)[:max_groups]
    chunks = [" ".join(v) for _, v in groups]

    # Söylem içeren ilk cümle birinci kümeye yoksa ekle
    say_sents = [s for s in sentences if SAY_VERBS_RE.search(s)]
    if say_sents and chunks and say_sents[0] not in chunks[0]:
        chunks[0] = (say_sents[0].rstrip(" .") + ". ") + chunks[0]

    return [normalize_spaces(c) for c in chunks]

# ———————————————————————————————————————
# Özet sıkıştırma (1–2 cümle, 220 karakter tavan)
# ———————————————————————————————————————
def compress_sentences(text: str, max_sent: int = 2, max_chars: int = 220) -> str:
    sents = RE_SENTENCE_SPLIT.split(text)
    sents = [s.strip() for s in sents if s.strip()]
    out, total = [], 0
    for s in sents:
        if len(out) >= max_sent:
            break
        if total + len(s) > max_chars:
            break
        out.append(s)
        total += len(s)
    return " ".join(out)

# ———————————————————————————————————————
# Ana API
# ———————————————————————————————————————
def process_rss_item(raw_text: str, meta: Optional[Dict] = None) -> ProcessResult:
    """
    Ham metni düzeltir ve 1..N kısa özet döner.
    - Hallüsinasyon yok; emin olmadıklarına dokunmaz.
    - Kısaltma eklerini apostrofla düzeltir (güvenli küme).
    - Aynı cümlede açık kurum varken 'Başkanı <İsim>' güvenli tamamlanır.
    - Alıntılar söylem fiiliyle tırnaklanır (çok uzun cümlelerde el sürmez).
    - Çok konulu metin 1–3 gruba bölünür; her grup 1–2 cümlede sıkıştırılır.
    """
    text = normalize_spaces(raw_text or "")
    text = common_soft_fixes(text)
    text = fix_apostrophes_for_acronyms(text)
    text = complete_missing_titles(text)     # sadece güvenli durum
    text = insert_missing_quotes(text)       # sadece tırnaksız kısa alıntılar

    topic_chunks = split_into_topics(text, max_groups=3)
    summaries: List[Summary] = [Summary(text=compress_sentences(c), topic=None) for c in topic_chunks]
    return ProcessResult(summaries=summaries, cleaned_text=text)

# ———————————————————————————————————————
# Hızlı test
# ———————————————————————————————————————
if __name__ == "__main__":
    demo = (
        'Lider, “Reformlar hızla sürecek” dedi. ABD yönetimi bu yıl yeni paket açıkladı. '
        'Başkanı John Doe, Brüksel’de basın toplantısına katıldı. NATO zirvesinde güvenlik başlığı öne çıktı.'
    )
    r = process_rss_item(demo)
    print("— Cleaned —")
    print(r.cleaned_text)
    print("— Summaries —")
    for s in r.summaries:
        print("-", s.text)
