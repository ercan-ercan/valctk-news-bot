#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_rss_bot.py
- RSS'ten haber alır, sayfa içeriğini indirir.
- 5N1K (Ne, Kim, Nerede, Ne zaman, Neden/Nasıl) kısa özet çıkarır; NOKTALAMA düzgün.
- Spor ceza haberlerinde "Takım: neden (tutar?)" satırları da eklenir.
- Tweet: Başlık + 5N1K maddeleri (+ varsa Ceza satırları), LINK PAYLAŞMAZ.
- Filtre: gündem/ekonomi/siyaset/spor/sosyal + Apple/Samsung (X etkileşimi odaklı).
- Dedup: rss_state.json (aynı haber tekrar atılmaz).
"""

import os, sys, json, time, argparse, re, datetime
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import feedparser
import tweepy
from dotenv import load_dotenv

# ========== FİLTRE ==========  (gündem + Apple/Samsung)
KEYWORDS = [
    # Politika & Ekonomi
    "son dakika","sondakika","seçim","cumhurbaşkanı","bakan","meclis",
    "zam","asgari ücret","enflasyon","faiz","dolar","euro","vergi","emekli","maaş","bütçe",
    "açıklandı","resmen","pfdk","tff","bddk","mb", "merkez bankası",
    # Felaket & Kriz
    "deprem","yangın","fırtına","sel","patlama","saldırı",
    "trafik kazası","kaza","öldü","yaralı","ölüm","gözaltı","tutuklandı","ceza","katliam",
    # Spor
    "maç","transfer","derbi","hakem","sakatlık","kadro",
    "beşiktaş","galatasaray","fenerbahçe","trabzonspor","milli takım","pfdk",
    "arda güler","kenan yıldız","icardi","muslera",
    # Sosyal & Trend
    "kadın","çocuk","adalet","kavga","tepki çekti","gündem oldu","video","görüntü",
    # Teknoloji (Apple/Samsung öne)
    "apple","iphone","ios","macbook","samsung","galaxy","android","yapay zeka","ai",
    # Dünya
    "gazze","israil","iran","putin","trump","abd","nato","savaş","ateşkes"
]

STATE_PATH = "rss_state.json"

# Spor kulüpler listesi (ceza/karar özetler için)
TEAMS = [
    "Fenerbahçe","Galatasaray","Beşiktaş","Trabzonspor","Başakşehir","Kasımpaşa","Sivasspor","Rizespor",
    "Alanyaspor","Antalyaspor","Adana Demirspor","Hatayspor","Konyaspor","Göztepe","Kayserispor","Ankaragücü",
    "Samsunspor","Pendikspor","Gaziantep FK","İstanbulspor","Karagümrük","Bodrum FK","Eyüpspor","Kocaelispor",
]
TEAMS_LOWER = [t.lower() for t in TEAMS]
PENALTY_HINTS = [
    "ceza","pfdk","disiplin","para cezası","ihtar","seyircisiz",
    "saha olay","kötü tezahürat","talimata aykırı","sportmenliğe aykırı",
    "kırmızı kart","sarı kart","hakeme","temsilciye","merdiven boşluğu",
    "meşale","yabancı madde","usulsüz","gecikme"
]
AMOUNT_RE = re.compile(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:TL|₺)', re.IGNORECASE)

# HTTP
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ValctkNewsBot/1.0)"}

# ---------- Yardımcılar ----------
def load_env_or_die():
    load_dotenv()
    for k in ["API_KEY","API_SECRET","ACCESS_TOKEN","ACCESS_TOKEN_SECRET","BEARER_TOKEN"]:
        if not os.getenv(k):
            raise SystemExit(f".env eksik: {k}")

def tw_client():
    return tweepy.Client(
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
        bearer_token=os.getenv("BEARER_TOKEN"),
        wait_on_rate_limit=False
    )

def load_sources(path="rss_sources.txt"):
    if not os.path.exists(path):
        raise SystemExit("rss_sources.txt bulunamadı.")
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    if not out:
        raise SystemExit("rss_sources.txt boş.")
    return out

def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        return json.load(open(STATE_PATH, "r", encoding="utf-8"))
    except Exception:
        return {}

def save_state(state):
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def entry_uid(e):
    return e.get("id") or e.get("link")

def fetch_feed(url):
    return feedparser.parse(url)

def normalize_punct(s: str) -> str:
    if not s: return s
    s = s.replace(" ,", ",").replace(" .", ".")
    s = s.replace(" !", "!").replace(" ?", "?").replace(" :", ":")
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

# ---------- İçerik indir & ayrıştır ----------
def fetch_article_text(link: str) -> str:
    try:
        r = requests.get(link, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except Exception:
        return ""
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script","style","noscript","header","footer","nav","aside"]):
        tag.decompose()

    candidates = []
    candidates += soup.select("div.haber_metni, div#NewsDetail, div.news-detail, article")
    candidates += soup.select("article, div.article, div.entry, div.content, div#content")

    blocks = []
    for c in candidates or [soup]:
        for li in c.select("li"):
            t = li.get_text(" ", strip=True)
            if len(t) > 2: blocks.append(t)
        for p in c.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 2: blocks.append(t)
    if not blocks:
        return soup.get_text(" ", strip=True)
    return "\n".join(blocks)

def split_sentences(text: str):
    parts = re.split(r'(?<=[\.\!\?])\s+', text)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out

# ---------- Spor cezaları ----------
def summarize_reason(sentence: str) -> str:
    s = sentence.lower()
    for key in ["para cezası","kötü tezahürat","saha olay","talimata aykırı","sportmenliğe aykırı",
                "kırmızı kart","yabancı madde","merdiven boşluğu","hakeme","temsilciye","usulsüz","gecikme"]:
        if key in s:
            return key
    return sentence[:60] + ("…" if len(sentence) > 60 else "")

def extract_penalties(article_text: str):
    if not article_text: return {}
    res = {}
    for sent in split_sentences(article_text):
        low = sent.lower()
        if not any(h in low for h in PENALTY_HINTS):
            continue
        teams_in = [orig for orig, lowname in zip(TEAMS, TEAMS_LOWER) if lowname in low]
        if not teams_in: 
            continue
        amt = None
        m = AMOUNT_RE.search(sent)
        if m: amt = m.group(0)
        why = summarize_reason(sent)
        for team in teams_in:
            res.setdefault(team, [])
            if (why, amt) not in res[team]:
                res[team].append((why, amt))
    return res

# ---------- 5N1K özet ----------
WHEN_RE = re.compile(r'\b(?:bugün|yarın|dün|bu akşam|bu sabah|\d{1,2}\s*(?:Ekim|Kasım|Aralık|Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos)\s*\d{4}?)\b', re.IGNORECASE)
WHERE_HINTS = ["İstanbul","Ankara","İzmir","Bursa","Kocaeli","Antalya","Adana","Trabzon","Kiev","Gazze","ABD","AB","NATO","Rusya","Türkiye"]

def extract_5n1k(title: str, text: str):
    # Ne?
    what = title.strip()

    who = ""
    where = ""
    when = ""
    whyhow = ""

    sents = split_sentences(text)
    first = sents[:6]  # ilk paragraflarla sınırlı tut

    # Kim: özel ad/kurum/kurul vb. yanıt sinyalleri
    # basitçe başlıktan ve ilk cümlelerden kurum/kişi yakalamaya çalış
    candidates = []
    for s in [title] + first:
        for m in re.findall(r'\b([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+){0,2})\b', s):
            # kısa stopword filtresi
            if m.lower() in ["son","dakika","türkiye","bugün","yarın","dün"]:
                continue
            candidates.append(m)
    if candidates:
        who = ", ".join(list(dict.fromkeys(candidates))[:3])

    # Nerede
    for w in WHERE_HINTS:
        if w.lower() in (text.lower()):
            where = w
            break

    # Ne zaman
    mw = WHEN_RE.search(" ".join(first))
    if mw:
        when = mw.group(0).strip().capitalize()

    # Neden/Nasıl
    # anahtar ipuçlarını ara
    for s in first:
        low = s.lower()
        if any(k in low for k in ["nedeni","sebebi","bu yüzden","dolayısıyla","gerekçe","açıklamasında","kararı","kararla","duyurdu","açıkladı","karar verildi","yapılacak","uyarı"]):
            whyhow = s
            break
    if not whyhow and first:
        whyhow = first[0]

    # temizle & kısalt
    def clamp(x, n=120):
        x = normalize_punct(x)
        return x if len(x) <= n else (x[:n-1] + "…")
    return {
        "Ne": clamp(what, 120),
        "Kim": clamp(who, 80) if who else "",
        "Nerede": clamp(where, 40) if where else "",
        "Ne zaman": clamp(when, 40) if when else "",
        "Neden/Nasıl": clamp(whyhow, 160) if whyhow else ""
    }

# ---------- Tweet derleme ----------
def build_tweet(title: str, article_text: str) -> str:
    penalties = extract_penalties(article_text)
    lines = [normalize_punct(title)]

    # Spor-PFDK gibi ise: takımlar
    if penalties:
        # büyükler önce
        prio = ["Fenerbahçe","Galatasaray","Beşiktaş","Trabzonspor"]
        ordered = [t for t in prio if t in penalties] + [t for t in penalties if t not in prio]
        for team in ordered[:6]:
            reasons = penalties[team][:2]
            parts = []
            for why, amt in reasons:
                parts.append(why + (f" ({amt})" if amt else ""))
            lines.append(f"- {team}: " + "; ".join(parts))

    # 5N1K bloğu
    summ = extract_5n1k(title, article_text)
    for label in ["Ne","Kim","Nerede","Ne zaman","Neden/Nasıl"]:
        if summ.get(label):
            lines.append(f"{label}: {summ[label]}")

    # 280 koruması
    text = "\n".join(lines)
    if len(text) > 280:
        # Önce 5N1K'yı kıs
        keep = [lines[0]]
        for ln in lines[1:]:
            if len("\n".join(keep + [ln])) <= 280:
                keep.append(ln)
            else:
                break
        text = "\n".join(keep)
    return text

# ========== ANA AKIŞ ==========
def main():
    ap = argparse.ArgumentParser(description="RSS -> Twitter (5N1K, ceza özeti, link yok)")
    ap.add_argument("--max-posts", type=int, default=2)
    ap.add_argument("--per-feed", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_env_or_die()
    client = tw_client()
    sources = load_sources()
    state = load_state()

    posted = 0
    for url in sources:
        if posted >= args.max_posts: break
        print(f"\n[FEED] {url}")
        st = state.get(url, {"seen": []})
        seen = set(st.get("seen", []))

        feed = fetch_feed(url)
        entries = feed.entries if getattr(feed, "entries", None) else []

        def ent_key(e):
            dt = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
            return time.mktime(dt) if dt else 0
        entries = sorted(entries, key=ent_key)

        new_entries = []
        for e in entries:
            uid = entry_uid(e)
            if uid and uid not in seen:
                new_entries.append(e)

        if not new_entries:
            print("  yeni haber yok.")
            continue

        take = min(len(new_entries), args.per_feed, args.max_posts - posted)
        for e in new_entries[-take:]:
            uid = entry_uid(e)
            title = (getattr(e, "title", "") or "").strip()
            link = (getattr(e, "link", "") or "").strip()
            summary = getattr(e, "summary", "") or getattr(e, "subtitle", "")
            if not title or not link: 
                continue

            # Filtre
            hay = (title + " " + summary).lower()
            if not any(k in hay for k in KEYWORDS):
                print(f"  (filtre dışı) {title[:90]}…")
                continue

            # Sayfayı indir → özet üret
            article_text = fetch_article_text(link)
            tweet_text = build_tweet(title, article_text)

            print("\n--- TWEET ---")
            print(tweet_text)

            if args.dry:
                print("→ Dry-run (gönderilmedi).")
            else:
                try:
                    r = client.create_tweet(text=tweet_text)
                    tid = r.data.get("id") if r and r.data else "unknown"
                    print(f"→ Gönderildi. ID: {tid}")
                    posted += 1
                    st.setdefault("seen", []).append(uid)
                    if len(st["seen"]) > 1000:
                        st["seen"] = st["seen"][-500:]
                except tweepy.TooManyRequests:
                    print("→ Rate limit (POST). Çıkılıyor.")
                    save_state(state); sys.exit(0)
                except Exception as ex:
                    print(f"→ Hata: {ex}")

            if posted >= args.max_posts: break

        state[url] = st
        save_state(state)

    print(f"\nBitti. Toplam gönderilen: {posted}")

if __name__ == "__main__":
    main()
