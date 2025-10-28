#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import csv
import time
import math
import textwrap
import requests
from datetime import datetime, timedelta, timezone

DRY = os.environ.get("DRY_MODE", "false").lower() == "true"

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")

# ---- Twitter ----
import tweepy

def tweepy_client():
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

# ---- Veri kaynağı: Stooq ----
# usdntry, eurtry, gbptry, xauusd (ons altın / USD)
STOOQ_URL = "https://stooq.com/q/l/?s={symbols}&i=d"

def fetch_stooq_latest(symbols):
    """Stooq list API tek satırlık CSV döndürür. close değerlerini alır."""
    url = STOOQ_URL.format(symbols=",".join(symbols))
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    # CSV satırlarını çöz
    lines = r.text.strip().splitlines()
    out = {}
    reader = csv.reader(lines)
    for row in reader:
        # Beklenen sıra: Symbol,Date,Time,Open,High,Low,Close,Volume
        if len(row) < 7: 
            continue
        sym = row[0].strip().lower()
        try:
            close = float(row[6])
        except Exception:
            continue
        out[sym] = close
    return out

def fetch_fx_snapshot():
    syms = ["usdntry", "eurtry", "gbpntry", "xauusd"]  # gbpntry bazı anlarda yok; sorun değil
    data = fetch_stooq_latest(syms)

    usd_try = data.get("usdntry")
    eur_try = data.get("eurtry")
    gbp_try = data.get("gbpntry")  # olmayabilir
    xau_usd = data.get("xauusd")

    if not usd_try or not eur_try or not xau_usd:
        raise RuntimeError("Kurlar alınamadı (Stooq)")

    # Gram altın ≈ ons altın(USD) * USD/TRY / 31.1035
    gram_altin = (xau_usd * usd_try) / 31.1035

    return {
        "USD/TRY": usd_try,
        "EUR/TRY": eur_try,
        "GBP/TRY": gbp_try,          # None olabilir
        "Gram Altın": gram_altin,
        "Ons Altın (USD)": xau_usd,
    }

# ---- Kart görseli (Pillow ile) ----
from PIL import Image, ImageDraw, ImageFont

BG_PATH = os.environ.get("FX_BG_PATH", "assets/fx_bg.jpg")  # repo: assets/fx_bg.jpg
FONT_PATH = os.environ.get("FX_FONT_PATH")  # opsiyonel; yoksa sistem fontu
TITLE = "GÜN KAPANIŞI (TL)"

def format_price(x):
    if x is None:
        return "-"
    # 2 ondalık yeterli (altında 1–2 kuruş oynayabilir)
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def build_card(data):
    # Arkaplan
    bg = Image.open(BG_PATH).convert("RGB")
    # 16:9 kırpma (Twitter önizleme dostu)
    W, H = bg.size
    target_ratio = 16/9
    cur_ratio = W/H
    if cur_ratio > target_ratio:
        # fazla geniş → yatay kırp
        new_w = int(H * target_ratio)
        offset = (W - new_w) // 2
        bg = bg.crop((offset, 0, offset + new_w, H))
    else:
        # fazla uzun → dikey kırp
        new_h = int(W / target_ratio)
        offset = (H - new_h) // 2
        bg = bg.crop((0, offset, W, offset + new_h))

    draw = ImageDraw.Draw(bg)

    # Yazı tipleri
    try:
        if FONT_PATH and os.path.exists(FONT_PATH):
            font_title = ImageFont.truetype(FONT_PATH, 72)
            font_item  = ImageFont.truetype(FONT_PATH, 56)
            font_small = ImageFont.truetype(FONT_PATH, 36)
        else:
            font_title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 72)
            font_item  = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 56)
            font_small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 36)
    except:
        font_title = ImageFont.load_default()
        font_item  = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Yarı saydam panel
    panel = Image.new("RGBA", bg.size, (0,0,0,0))
    pdraw = ImageDraw.Draw(panel)
    pdraw.rectangle([40,40,bg.width-40,bg.height-40], fill=(0,0,0,120), outline=(255,255,255,140), width=2)
    bg = Image.alpha_composite(bg.convert("RGBA"), panel).convert("RGB")

    draw = ImageDraw.Draw(bg)

    # Başlık
    draw.text((70, 70), TITLE, font=font_title, fill=(255,255,255))

    y = 170
    step = 85
    items = [
        ("USD/TRY", data["USD/TRY"]),
        ("EUR/TRY", data["EUR/TRY"]),
        ("GBP/TRY", data["GBP/TRY"]),
        ("Gram Altın", data["Gram Altın"]),
    ]
    for name, val in items:
        line = f"{name}: {format_price(val)}"
        draw.text((70, y), line, font=font_item, fill=(255,255,255))
        y += step

    # Alt bilgi
    ts = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    foot = f"Kaynak: Stooq | Ons Altın (USD): {format_price(data['Ons Altın (USD)'])} | {ts} (TR)"
    draw.text((70, bg.height-90), foot, font=font_small, fill=(220,220,220))

    # Byte’a yaz
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=88)
    buf.seek(0)
    return buf

def build_text(data):
    # Tweet metni (2 satır, sade)
    parts = [
        f"USD {format_price(data['USD/TRY'])} • EUR {format_price(data['EUR/TRY'])} • GBP {format_price(data['GBP/TRY'])}",
        f"Gram altın {format_price(data['Gram Altın'])} TL  •  Ons {format_price(data['Ons Altın (USD)'])} $",
    ]
    return "\n".join(parts)

def main():
    try:
        data = fetch_fx_snapshot()
    except Exception as e:
        print(f"Veri alınamadı: {e}")
        print("⚠️ Veriler alınamadı, tweet atlanıyor.")
        return

    text = build_text(data)
    img_buf = build_card(data)

    if DRY:
        print(text)
        print("DRY-MODE: görsel üretildi, tweet edilmedi.")
        return

    api = tweepy_client()

    # Medya yükle
    media = api.media_upload(filename="fx.jpg", file=img_buf)
    # Tweet at
    api.update_status(status=text, media_ids=[media.media_id])

if __name__ == "__main__":
    main()
