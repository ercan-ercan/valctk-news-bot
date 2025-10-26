#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_rss_bot.py
- RSS'lardan haber çeker.
- Sayfa içeriğinden kısa, net ve tek-paragraf özet üretir (5N1K YOK).
- Noktalama/boşluk düzeltme, 260 civarı hedef; 280 hard limit.
- DRY modunda state'e yazmaz; sadece gerçek gönderimde "seen" günceller.
- V2 poster: tweepy.Client.create_tweet (v1.1 yok! 403/453 çözümü)
- Çöp içerik (kampanya/kilosu/tarif vb.) negatif filtre ile elenir.
- Üstte bağıran kategori başlıklarını (SPOR HABERLERİ vs.) kırpar.
"""

import os, json, time, re, argparse
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import feedparser
import tweepy
from dotenv import load_dotenv

# ----------- Ayarlar -----------
MAX_TWEET_LEN = 280
TARGET_LEN = 260
STATE_FILE = "rss_state.json"
SOURCES_FILE = "rss_sources.txt"

# Pozitif konu anahtarları (haber değeri)
KEYWORDS = [
    # ekonomi/finans
    "dolar","euro","faiz","enflasyon","bütçe","zam","asgari","mb","merkez bankası",
    # acil/gündem
    "son dakika","deprem","yangın","sel","patlama","saldırı","kaza","gözaltı","tutuklandı",
    # siyaset/karar
    "cumhurbaşkanı","bakan","kabine","meclis","kararname","resmi gazete","yasa","seçim",
    # spor (magazin değil maç/karar/puan)
    "maç","derbi","kadro","puan","transfer","pfdk","tff","şampiyonlar ligi",
    # teknoloji/iş
    "apple","iphone","samsung","galaxy","yapay zeka","yatırım","ihracat","ithalat","anlaşma",
    # dünya
    "gazze","israil","iran","rusya","putin","abd","ab","nato","ateşkes","savaş"
]

# Negatif filtre – çöp/infotainment ayıklama
NEGATIVE = [
    "kilosu","kilo","tarif","nasıl yapılır","lezzet","kampanya","indirim",
    "burç","yemek tarifi","sağlık tüyosu","güzellik sırrı","şifalı",
    "nar ekşisi","ev hanımları","trend kombin","diyet listesi","şok etti fiyat"
]

UA = {"User-Agent": "Mozilla/5.0 (compatible; ValctkNewsBot/1.0)"}

# ----------- Yardımcılar -----------

def normalize_ws(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return (s.replace(" ,", ",")
             .replace(" .", ".")
             .replace(" !", "!")
             .replace(" ?", "?"))

def safe_read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def safe_write_json(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def strip_shouty_prefix(text: str) -> str:
    """
    Bağıran kategori başlıklarını kırp:
    'SPOR HABERLERİ ...', 'EKONOMİ ...' vb.
    """
    t = text.lstrip()
    # Baştaki tam büyük harfli blokları temizle
    t = re.sub(r"^(?:[A-ZÇĞİÖŞÜ]{3,}(?:\s+[A-ZÇĞİÖŞÜ]{2,}){0,3})[:\-–—]?\s+", "", t)
    # Çift başlık benzeri artıkları da temizle
    t = re.sub(r"^(?:HABERLERİ|GÜNDEM|EKONOMİ|SPOR|MAGAZİN)\s+", "", t, flags=re.I)
    return t.strip()

def clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for t in soup(["script","style","noscript","header","footer","nav","aside"]):
        t.decompose()
    # Makale gövdesi seçicileri
    node = None
    for sel in [
        "article", "div[itemprop='articleBody']", ".article-body", ".news-content",
        ".content", ".post-content", "#content", ".article"
    ]:
        node = soup.select_one(sel)
        if node and len(node.get_text()) > 200:
            break
    base = node if node else soup
    parts = []
    for el in base.find_all(["p","li"]):
        txt = el.get_text(" ", strip=True)
        if len(txt) > 30:
            parts.append(txt)
    if not parts:
        parts = [base.get_text(" ", strip=True)]
    text = normalize_ws(" ".join(parts))
    # site ortak bağıran ibareler
    text = re.sub(r"\b(Fotoğraf|Video|SON DAKİKA|GÜNCELLEME)\b:?","", text, flags=re.I)
    # baştaki kategori bağırışlarını kırp
    text = strip_shouty_prefix(text)
    return text

def fetch_article_text(url: str) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=10)
        r.raise_for_status()
        return clean_html_to_text(r.text)
    except Exception:
        return ""

def first_sentences(text: str, max_chars: int) -> str:
    text = normalize_ws(text)
    # cümlelere böl
    parts = re.split(r"(?<=[.!?])\s+", text)
    if not parts: 
        return ""
    out = ""
    for p in parts:
        p = strip_shouty_prefix(normalize_ws(p))
        # çok jenerik bildirim cümleleri
        if re.search(r"(açıklandı|bildirildi|ifade edildi|kaydedildi)[: ]?$", p, re.I):
            continue
        # tarih/saat yalnız satır
        if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}", p):
            continue
        cand = (out + (" " if out else "") + p).strip()
        if len(cand) <= max_chars:
            out = cand
        else:
            break
    if not out:
        out = parts[0][:max_chars].rstrip()
    if not re.search(r"[.!?…]$", out):
        out += "."
    return out

def compress(text: str, max_chars: int) -> str:
    text = normalize_ws(text)
    if len(text) <= max_chars:
        return text
    # parantez içini kıs
    text = re.sub(r"\([^)]{15,}\)", "", text)
    text = normalize_ws(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars-1].rstrip() + "…"

def looks_newsworthy(title: str, desc: str) -> bool:
    blob = f"{title} {desc}".lower()
    if any(x in blob for x in NEGATIVE):
        return False
    return any(k in blob for k in KEYWORDS)

def build_tweet(title: str, body: str) -> str:
    title = strip_shouty_prefix(normalize_ws(title))
    sent = first_sentences(body, TARGET_LEN)
    if title and sent and title.lower() in sent.lower():
        text = compress(sent, MAX_TWEET_LEN)
    else:
        merged = f"{title}. {sent}" if title else sent
        text = compress(merged, MAX_TWEET_LEN)
    return text

def load_sources():
    if not Path(SOURCES_FILE).exists():
        return []
    out = []
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return out

# ----------- Ana Akış -----------

def run_bot(dry: bool, max_posts: int, per_feed: int):
    state = safe_read_json(STATE_FILE, {"seen": []})
    seen = set(state.get("seen", []))
    prepared = sent = skipped = 0

    load_dotenv()
    client = None
    if not dry:
        # v2 Client (user context)
        client = tweepy.Client(
            consumer_key=os.getenv("API_KEY"),
            consumer_secret=os.getenv("API_SECRET"),
            access_token=os.getenv("ACCESS_TOKEN"),
            access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
            bearer_token=os.getenv("BEARER_TOKEN"),
            wait_on_rate_limit=True,
        )

    total = 0
    for feed_url in load_sources():
        if total >= max_posts: break
        print(f"\n[FEED] {feed_url}")

        try:
            f = feedparser.parse(feed_url)
            entries = f.entries[: per_feed]
        except Exception:
            continue

        for it in entries:
            if total >= max_posts: break

            title = getattr(it, "title", "") or ""
            link  = getattr(it, "link", "") or ""
            summ  = getattr(it, "summary", "") or ""

            key = link or title
            if not key:
                skipped += 1
                continue

            # DRY'da seen KONTROLÜ var ama seen'E EKLEME YOK
            if key in seen:
                skipped += 1
                continue

            if not looks_newsworthy(title, summ):
                skipped += 1
                continue

            body = fetch_article_text(link) if link else summ
            raw = body if len(body) > 80 else summ
            tweet = build_tweet(title, raw)

            if len(tweet) < 30:
                skipped += 1
                continue

            print("\n--- TWEET ---")
            print(tweet)
            prepared += 1

            if dry:
                print("→ DRY-MODE (tweet edilmedi).")
            else:
                try:
                    client.create_tweet(text=tweet)
                    print("→ Gönderildi (v2).")
                    sent += 1
                    seen.add(key)  # SADECE GERÇEKTE işaretle
                except tweepy.TweepyException as e:
                    print(f"→ Hata (v2): {e}")
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        safe_write_json(STATE_FILE, {"seen": list(seen)})
                        return prepared, sent, skipped

            total += 1
            time.sleep(1.0)

    if not dry:
        safe_write_json(STATE_FILE, {"seen": list(seen)})
    return prepared, sent, skipped

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-posts", type=int, default=3)
    ap.add_argument("--per-feed", type=int, default=2)
    args = ap.parse_args()

    prepared, sent, skipped = run_bot(args.dry, args.max_posts, args.per_feed)
    print(f"\nHazırlanan: {prepared} | Gönderilen: {sent} | Atlanan: {skipped}")

if __name__ == "__main__":
    main()
