#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_rss_bot.py  —  API'siz özetleyici
- RSS'leri okur, sayfa içeriğini indirir (requests + bs4).
- Kural-tabanlı özet: kısa ve net; doğrudan alıntılar tırnak içinde.
- Liste/aday/takım gibi durumlarda madde madde; aksi halde akıcı 1–2 cümle.
- Link paylaşmaz. 280 karakter korumalı.
- Filtre: gündem/siyaset/ekonomi/spor/teknoloji/sosyal (X etkileşimi odaklı).
- Dedup: rss_state.json (aynı haber tekrar atılmaz).
"""

import os, sys, json, time, argparse, re
from typing import List, Tuple, Dict
import requests, feedparser, tweepy
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ================== AYARLAR ==================
STATE_PATH = "rss_state.json"

RSS_SOURCES_DEFAULT = [
    "http://sondakika.haber7.com/sondakika.rss",
    "https://www.sozcu.com.tr/feeds-son-dakika",
    "https://www.sabah.com.tr/rss/sondakika.xml",
    "https://feeds.bbci.co.uk/turkce/rss.xml",
    "https://www.cnnturk.com/feed/rss/all/news",
    "https://www.ntv.com.tr/rss",
    "https://www.hurriyet.com.tr/rss/anasayfa",
]

# X dili/konu filtresi (alt-case arama)
KEYWORDS = [
    # Politika & Ekonomi
    "son dakika","sondakika","seçim","cumhurbaşkanı","bakan","meclis",
    "zam","asgari ücret","enflasyon","faiz","dolar","euro","vergi","emekli","maaş","bütçe",
    "açıklandı","resmen","pfdk","tff","bddk","mb","merkez bankası",
    # Felaket & Kriz
    "deprem","yangın","fırtına","sel","patlama","saldırı",
    "gözaltı","tutuklandı","ceza","katliam",
    # Spor
    "maç","transfer","derbi","hakem","sakatlık","kadro",
    "beşiktaş","galatasaray","fenerbahçe","trabzonspor","milli takım","pfdk",
    "arda güler","kenan yıldız","icardi","muslera",
    # Sosyal & Trend
    "kadın","çocuk","adalet","kavga","tepki çekti","gündem oldu","video","görüntü",
    # Teknoloji
    "apple","iphone","ios","macbook","samsung","galaxy","android","yapay zeka","ai",
    # Dünya
    "gazze","israil","iran","putin","trump","abd","nato","savaş","ateşkes",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ValctkNewsBot/2.0)"}

# Spor kulüpleri (liste tespiti ve öncelik)
TEAMS = [
    "Fenerbahçe","Galatasaray","Beşiktaş","Trabzonspor","Başakşehir","Kasımpaşa","Sivasspor","Rizespor",
    "Alanyaspor","Antalyaspor","Adana Demirspor","Hatayspor","Konyaspor","Göztepe","Kayserispor","Ankaragücü",
    "Samsunspor","Pendikspor","Gaziantep FK","İstanbulspor","Karagümrük","Bodrum FK","Eyüpspor","Kocaelispor",
]
TEAMS_L = [t.lower() for t in TEAMS]

# ================== YARDIMCILAR ==================
def load_env_or_die():
    load_dotenv()
    need = ["API_KEY","API_SECRET","ACCESS_TOKEN","ACCESS_TOKEN_SECRET","BEARER_TOKEN"]
    miss = [k for k in need if not os.getenv(k)]
    if miss:
        raise SystemExit("Eksik .env: " + ", ".join(miss))

def tw_client():
    return tweepy.Client(
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
        bearer_token=os.getenv("BEARER_TOKEN"),
        wait_on_rate_limit=False
    )

def load_sources(path="rss_sources.txt") -> List[str]:
    if os.path.exists(path):
        out = []
        with open(path,"r",encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    out.append(s)
        if out: return out
    return RSS_SOURCES_DEFAULT[:]  # yedek

def load_state() -> Dict:
    if not os.path.exists(STATE_PATH): return {}
    try:
        return json.load(open(STATE_PATH,"r",encoding="utf-8"))
    except Exception:
        return {}

def save_state(st: Dict):
    json.dump(st, open(STATE_PATH,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def fetch_feed(url: str):
    return feedparser.parse(url)

def fetch_article(link: str) -> str:
    try:
        r = requests.get(link, headers=HEADERS, timeout=12)
        r.raise_for_status()
    except Exception:
        return ""
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script","style","noscript","header","footer","nav","aside"]):
        tag.decompose()
    # muhtemel içerik kapları
    cand = soup.select("article, div.article, div.haber_metni, div.news-detail, div#NewsDetail, div.entry, div.content, main")
    if not cand: cand = [soup]
    chunks = []
    for c in cand:
        for li in c.select("li"):
            t = li.get_text(" ", strip=True)
            if len(t) > 2: chunks.append(t)
        for p in c.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 2: chunks.append(t)
    if not chunks:
        return soup.get_text(" ", strip=True)
    return "\n".join(chunks)

def normalize_spaces(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def sentences(text: str) -> List[str]:
    parts = re.split(r'(?<=[\.\!\?])\s+', text)
    return [p.strip() for p in parts if p and len(p.strip()) > 2]

def has_keyword(title: str, summary: str) -> bool:
    hay = (title + " " + (summary or "")).lower()
    return any(k in hay for k in KEYWORDS)

# ================== ÖZETLEYİCİ (kural tabanlı) ==================
NAME_RE = re.compile(r"\b([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+){0,2})\b")

def extract_names(text: str) -> List[str]:
    cands = []
    for m in NAME_RE.findall(text):
        low = m.lower()
        if low in {"son","dakika","türkiye","bugün","yarın","dün"}:
            continue
        cands.append(m.strip())
    # benzersiz sırayı koru
    uniq = []
    for x in cands:
        if x not in uniq:
            uniq.append(x)
    return uniq[:10]

def find_quoted(text: str) -> List[str]:
    out = []
    # Türkçe tırnak ve düz tırnak
    for m in re.findall(r"[“\"']([^\"”']{6,180})[\"”']", text):
        out.append(m.strip())
    return out[:2]

def detect_list_lines(text: str) -> List[str]:
    lines = [l.strip() for l in text.splitlines()]
    items = []
    for l in lines:
        if re.match(r"^[-••\*]\s+.{2,}", l):
            items.append(re.sub(r"^[-•\*]\s+", "", l))
    # virgül-listeleri de ayıkla
    if not items:
        m = re.search(r":\s*([A-ZÇĞİÖŞÜa-zçğıöşü0-9 ,\-\(\)\/]+)", text)
        if m and "," in m.group(1):
            parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
            if 2 <= len(parts) <= 10:
                items = parts
    # takım/aday listelerini sinyalle
    clean = []
    for it in items:
        it = re.sub(r"\s{2,}", " ", it)
        it = re.sub(r"\s*\.+$", "", it)
        clean.append(it)
    return clean[:8]

def shorten(s: str, n: int) -> str:
    s = normalize_spaces(s)
    return s if len(s) <= n else (s[:n-1] + "…")

def build_summary(title: str, body: str) -> str:
    title = normalize_spaces(title)
    body = normalize_spaces(body)

    # 1) Çok bariz “liste haberi” ise madde madde
    items = detect_list_lines(body)
    if not items and any(word in title.lower() for word in ["aday","isim","kadro","kadroda","ceza","puan durumu","listesi"]):
        # başlıkta sinyal varsa, metinden isim/kurum topla
        names = extract_names(body)
        if len(names) >= 3:
            items = names[:6]

    # 2) Alıntı varsa bir cümle alıntı ekle
    quotes = find_quoted(title) or find_quoted(body)

    # 3) Spor kulüpleri özel: takım adlarını öne çek
    teams_in = [t for t in TEAMS if t.lower() in (title + " " + body).lower()]
    is_sports_list = len(teams_in) >= 1 and ( "ceza" in body.lower() or "transfer" in body.lower() or "kadro" in body.lower())

    # 4) Özet metni oluştur
    if items or is_sports_list:
        # Madde madde + başlık (başlık sade)
        head = shorten(title, 140)
        lines = [head]
        if is_sports_list and teams_in:
            # büyükleri öne al
            prio = ["Fenerbahçe","Galatasaray","Beşiktaş","Trabzonspor"]
            ordered = [t for t in prio if t in teams_in] + [t for t in teams_in if t not in prio]
            for t in ordered[:6]:
                lines.append(f"- {t}")
        # genel liste
        for it in items[:6]:
            # isim/aday dizisi gibi olanları direkt yaz
            lines.append(f"- {it}")
        # alıntı ekle (varsa ve yer kalırsa)
        if quotes:
            q = f"“{quotes[0]}”"
            if len("\n".join(lines + [q])) <= 280:
                lines.append(q)
        text = "\n".join(lines)
        return shorten(text, 280)

    # 5) Normal akış: 1–2 cümle net özet
    sents = sentences(body)
    lead = ""
    for s in sents[:6]:
        # çok genel ve reklamsı girişleri ele
        if any(w in s.lower() for w in ["reklam","çerez","kabul ederek","okumak için tıklayın"]):
            continue
        lead = s
        break
    if not lead:
        lead = title

    # Alıntı ekle (tek cümle içine)
    text = shorten(title, 120)
    if quotes:
        q = f" “{quotes[0]}”"
        text = shorten(text + q, 160)

    # Lead'i sonuna ekle (gerekiyorsa)
    if lead and lead.lower() not in text.lower():
        merged = f"{text}. {lead}"
        return shorten(merged, 280)

    return shorten(text, 280)

# ================== ANA AKIŞ ==================
def run_bot(dry: bool, max_posts: int, per_feed: int) -> Tuple[int,int,int]:
    client = tw_client()
    sources = load_sources()
    state = load_state()
    prepared = sent = skipped = 0

    for url in sources:
        if sent >= max_posts:
            break
        print(f"\n[FEED] {url}")
        seen = set(state.get(url, {}).get("seen", []))
        feed = fetch_feed(url)
        entries = feed.entries if getattr(feed, "entries", None) else []

        # zamana göre sırala (eski -> yeni)
        def ent_key(e):
            dt = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
            return time.mktime(dt) if dt else 0
        entries = sorted(entries, key=ent_key)

        # yeni olanları çek
        fresh = []
        for e in entries:
            uid = e.get("id") or e.get("link")
            if uid and uid not in seen:
                fresh.append(e)

        if not fresh:
            continue

        take = min(len(fresh), per_feed, max_posts - sent)
        for e in fresh[-take:]:
            uid = e.get("id") or e.get("link")
            title = (getattr(e, "title", "") or "").strip()
            link  = (getattr(e, "link", "") or "").strip()
            summary = getattr(e, "summary", "") or getattr(e, "subtitle", "")
            if not title or not link:
                continue

            if not has_keyword(title, summary):
                skipped += 1
                continue

            body = fetch_article(link)
            tweet = build_summary(title, body)
            prepared += 1

            print("\n--- TWEET ---")
            print(tweet)

            if dry:
                print("→ DRY-MODE (tweet edilmedi).")
            else:
                try:
                    client.create_tweet(text=tweet)
                    sent += 1
                except tweepy.TooManyRequests:
                    print("→ Rate limit (429). Çıkılıyor.")
                    save_state(state)
                    return prepared, sent, skipped
                except tweepy.Forbidden as ex:
                    # 453/403 gibi
                    print(f"→ Hata: {ex}")
                except tweepy.Unauthorized as ex:
                    # 401
                    print(f"→ Yetkisiz (401). Anahtarları kontrol et. Ayrıntı: {ex}")
                except Exception as ex:
                    print(f"→ Hata: {ex}")

            # görüldü'ye ekle
            st = state.get(url, {"seen": []})
            st.setdefault("seen", []).append(uid)
            if len(st["seen"]) > 1000:
                st["seen"] = st["seen"][-500:]
            state[url] = st
            save_state(state)

            if sent >= max_posts:
                break

    print(f"\nHazırlanan: {prepared} | Gönderilen: {sent} | Atlanan: {skipped}")
    return prepared, sent, skipped

def main():
    ap = argparse.ArgumentParser(description="RSS -> Twitter (API'siz özet)")
    ap.add_argument("--max-posts", type=int, default=2)
    ap.add_argument("--per-feed", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_env_or_die()
    run_bot(args.dry, args.max_posts, args.per_feed)

if __name__ == "__main__":
    main()
