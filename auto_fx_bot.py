#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import csv
import requests
from datetime import datetime, timedelta, timezone

# ---- Modlar / Kimlikler ----
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
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    out = {}
    reader = csv.reader(r.text.strip().splitlines())
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
    syms = ["usdntry", "eurtry", "gbptry", "xauusd"]  # GBP sembolü düzeltildi
    data = fetch_stooq_latest(syms)

    usd_try = data.get("usdntry")
    eur_try = data.get("eurtry")
    gbp_try = data.get("gbptry")
    xau_usd = data.get("xauusd")

    if not usd_try or not eur_try or not xau_usd:
        raise RuntimeError("Kurlar alınamadı (Stooq)")

    # Gram altın ≈ ons altın(USD) * USD/TRY / 31.1035
    gram_altin = (xau_usd * usd_try) / 31.1035

    return {
        "Dolar": usd_try,
        "Euro": eur_try,
        "Pound": gbp_try,          # None olabilir
        "Gram Altın": gram_altin,
        "Ons Altın (USD)": xau_usd,
    }

# ---- Kart görseli (Pillow) ----
from PIL import Image, ImageDraw, ImageFont

TITLE = "GÜN KAPANIŞI (TL)"

def _resolve_bg_path():
    """Arka plan dosyasını en iyi adrese göre seç."""
    candidates = [
        os.environ.get("BADGE_PATH"),
        os.environ.get("FX_BG_PATH"),
        "./guncel_kurlar 1.jpg",           # senin istediğin ad
        "./assets/assets/fx_bg.jpg",       # repodaki bilinen yol
        "./fx_bg.jpg",
        "./fx_card.png",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError("Arka plan görseli bulunamadı. BADGE_PATH ya da FX_BG_PATH ayarla veya dosyayı repo köküne koy.")

def format_price(x):
    if x is None:
        return "-"
    # 2 ondalık, TR yazımı (ondalık virgül)
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def build_card(data):
    bg_path = _resolve_bg_path()
    bg = Image.open(bg_path).convert("RGB")

    # 16:9 kırp (Twitter önizleme dostu)
    W, H = bg.size
    target_ratio = 16/9
    cur_ratio = W/H
    if cur_ratio > target_ratio:
        new_w = int(H * target_ratio)
        offset = (W - new_w) // 2
        bg = bg.crop((offset, 0, offset + new_w, H))
    else:
        new_h = int(W / target_ratio)
        offset = (H - new_h) // 2
        bg = bg.crop((0, offset, W, offset + new_h))

    draw = ImageDraw.Draw(bg)

    # Yazı tipleri
    try:
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
        ("Dolar", data["Dolar"]),
        ("Euro", data["Euro"]),
        ("Pound", data["Pound"]),
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
    # Tweet metni (2 satır, sade; slash yok)
    parts = [
        "Güncel Kurlar:",
        f"• Dolar: {format_price(data['Dolar'])}   Euro: {format_price(data['Euro'])}   Pound: {format_price(data['Pound'])}",
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
    # Medya yükle + Tweet at
    media = api.media_upload(filename="fx.jpg", file=img_buf)
    api.update_status(status=text, media_ids=[media.media_id])

if __name__ == "__main__":
    main()
