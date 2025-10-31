#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import html
import argparse
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
import tweepy

# ---- Ayarlar ----
UA = {"User-Agent": "Mozilla/5.0 (compatible; BundleScraper/2.0)"}
TIMEOUT = 12
MAX_TWEET = 280
TCO_RESERVE = 25  # t.co kısalması için kaba rezerv
DRY = os.environ.get("DRY_MODE", "false").lower() == "true"

# ---- Twitter v2 ----
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")

def tw_client_v2():
    return tweepy.Client(
        bearer_token=BEARER_TOKEN,
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True,
    )

# ---- Yardımcılar ----
def get_html(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def clean(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"\s+", " ", s).strip()
    # baştaki bullet vs.
    s = re.sub(r"^[•\u2022\-–—]\s*", "", s)
    return s

def extract_title(doc: BeautifulSoup) -> str:
    for sel in [["h1"], ["h2"]]:
        el = doc.find(sel[0])
        if el and el.get_text(strip=True):
            return clean(el.get_text(" ", strip=True))
    m = doc.find("meta", attrs={"property": "og:title"}) or doc.find("meta", attrs={"name": "og:title"})
    if m and m.get("content"):
        return clean(m["content"])
    if doc.title and doc.title.string:
        return clean(doc.title.string)
    return ""

def collect_following_texts(anchor) -> list[str]:
    """'Bundle AI / özetliyor' başlığını bulduktan sonra, yakın takip eden <li>/<p> metinlerini topla."""
    out = []
    # En fazla birkaç kardeş blok tarayalım ki saçmalamayalım
    for sib in anchor.find_all_next(limit=10):
        # başka bir başlığa geldiysek dur
        if sib.name in ("h1", "h2", "h3"):
            break
        # liste maddeleri
        if sib.name in ("ul", "ol"):
            for li in sib.find_all("li"):
                t = clean(li.get_text(" ", strip=True))
                if len(t) >= 3:
                    out.append(t)
        # paragraflar
        if sib.name in ("p", "div"):
            t = clean(sib.get_text(" ", strip=True))
            if len(t) >= 3:
                # bullet'lı paragrafı böl
                parts = [clean(x) for x in re.split(r"[•\u2022]\s*", t) if x.strip()]
                if parts:
                    out.extend(parts)
                else:
                    out.append(t)
        # yeterince topladıysak bırak
        if len(out) >= 6:
            break
    # tekrarları temizle
    dedup = []
    seen = set()
    for t in out:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup

def extract_ai_summary(doc: BeautifulSoup) -> list[str]:
    """Bundle AI 'özetliyor' bloğundaki tüm paragrafları/maddeleri döndür."""
    # 1) 'özet' içeren başlık/etiketleri yakala
    # Deprecation fix: string= ile ara
    anchors = []
    for tag in doc.find_all(string=re.compile(r"(Bundle\s*AI|özet|özetliyor)", re.I)):
        if tag.parent:
            anchors.append(tag.parent)

    for anc in anchors:
        texts = collect_following_texts(anc)
        if texts:
            return texts

    # 2) class/id içinde 'summary' geçen bloklardan topla
    for div in doc.find_all(attrs={"class": re.compile(r"summary|ai", re.I)}):
        lis = [clean(li.get_text(" ", strip=True)) for li in div.find_all("li")]
        lis = [x for x in lis if x]
        if lis:
            return lis
        ps = [clean(p.get_text(" ", strip=True)) for p in div.find_all("p")]
        ps = [x for x in ps if x]
        if ps:
            return ps

    return []

def fallback_description(doc: BeautifulSoup) -> str:
    for key in ("og:description", "twitter:description", "description"):
        m = doc.find("meta", attrs={"property": key}) or doc.find("meta", attrs={"name": key})
        if m and m.get("content"):
            return clean(m["content"])
    # ilk uzun paragrafa düş
    for p in doc.find_all("p"):
        txt = clean(p.get_text(" ", strip=True))
        if len(txt) > 120:
            return txt
    return ""

def smart_join(paragraphs: list[str]) -> str:
    """Paragrafları doğal bir akışla tek paragrafa indir (cümle birleşimi)."""
    # çok kısa cümleleri birleştir, aşırı tekrarları ele
    out = []
    for t in paragraphs:
        if not t:
            continue
        # çok benzer tekrarları at
        if out and t.lower() == out[-1].lower():
            continue
        out.append(t)
    joined = " ".join(out)
    # ardışık boşluk temizliği
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined

def natural_truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    # Noktalama/bosluk sınırında kesmeyi dene
    cut = text[:max_len]
    # En yakın doğal sınır: nokta, noktalı virgül, iki nokta, tire, virgül, boşluk
    m = re.search(r"[\.!?…;:\-–—,]\s+\S*?$", cut)
    if m:
        cut = cut[:m.start()].rstrip()
    else:
        # kelime sınırı
        if " " in cut:
            cut = cut[:cut.rfind(" ")].rstrip()
    return (cut + "…").rstrip()

def compose_tweet(full_summary: str, url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    tail = f" — Kaynak: {host} {url}"
    room = MAX_TWEET - len(tail) - 1  # 1 boşluk payı
    # t.co payını zaten kuyrukta gerçek URL var diye ayrıca TCO_RESERVE eklemiyoruz;
    # güvenli tarafta kalmak istersen: room -= TCO_RESERVE
    if room < 60:
        room = 60  # minimum biraz metin kalsın
    text = natural_truncate(full_summary, room)
    return f"{text}{tail}"

def make_tweet_from_bundle(url: str) -> str:
    doc = get_html(url)
    title = extract_title(doc)
    bullets = extract_ai_summary(doc)

    if bullets:
        full = smart_join(bullets)
    else:
        # AI özet bulunamadı; fallback'e düş
        desc = fallback_description(doc)
        if not desc and not title:
            raise RuntimeError("Sayfadan özet çekilemedi")
        full = desc or title

    # Başlık yoksa direkt özet; başlık varsa özet başına ekleyelim mi?
    # Bundle özet genelde başlığı kapsıyor; gereksiz tekrar olmasın.
    tweet = compose_tweet(full, url)
    return tweet

# ---- CLI ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Bundle haber URL")
    ap.add_argument("--dry", action="store_true", help="Sadece yazdır, tweet atma")
    args = ap.parse_args()

    tweet = make_tweet_from_bundle(args.url)

    if DRY or args.dry:
        print("— DRY RUN —")
        print(tweet)
        return

    client = tw_client_v2()
    client.create_tweet(text=tweet)
    print("✅ Tweet gönderildi.")

if __name__ == "__main__":
    main()
