#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_fx_bot.py — 18:01'de döviz/altın özetini, sabit bir görselle tweetler.
- Pillow yok; varolan görsel dosyasını (assets/doviz.jpg) media olarak ekler.
- Kısa, net ve resmi dilden uzak, temiz noktalama.
"""

import os, time, json, math
import requests
import tweepy

API_KEY             = os.getenv("API_KEY")
API_SECRET          = os.getenv("API_SECRET")
ACCESS_TOKEN        = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
BEARER_TOKEN        = os.getenv("BEARER_TOKEN")

FX_IMAGE_PATH       = os.getenv("FX_IMAGE_PATH", "assets/doviz.jpg")  # workflow env'de tanımlı

# ---- basit fiyat toplayıcılar (kaynaklar stabil değilse mevcut botundaki fonksiyonları kullan) ----
# Burada örnek olarak TradingView'in lightweight endpointlerinden kaçınmak için 
# Yahoo Finance benzeri basit JSON proxy'leri yerine, mevcut dosyandaki kaynak fonksiyonlarını koruman iyi olur.
# Eğer mevcut botunda çalışan get_rates() fonksiyonun varsa onu kullan.
# Aşağıdaki dummy fonksiyon, bir  yedek / örnek şablon:

def get_rates():
    """
    Dolar/TL, Euro/TL, Sterlin/TL ve Gram Altın için float döndür.
    Burayı kendi çalışan kaynaklarınla doldurmuştuk; onları kullan.
    """
    # --- ÖRNEK YER TUTUCU (gerçek veriyi kendi fonksiyonlarından çek) ---
    # raise NotImplementedError("Mevcut auto_fx_bot içindeki veri kaynaklarını burada kullan.")
    # Aşağıyı kendi fonksiyonlarınla değiştir:
    return {
        "USDTRY": None,
        "EURTRY": None,
        "GBPTRY": None,
        "GAU":    None,   # gram altın
    }

def fmt(v):
    return ("—" if v is None else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

def build_text(r):
    # emoji yok, kısa ve net
    lines = []
    lines.append("Gün sonu piyasa özeti:")
    lines.append(f"Dolar: {fmt(r['USDTRY'])} • Euro: {fmt(r['EURTRY'])} • Sterlin: {fmt(r['GBPTRY'])}")
    lines.append(f"Gram altın: {fmt(r['GAU'])}")
    return "\n".join(lines).strip()

# ---- Twitter client + media upload ----
def get_clients():
    client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
        bearer_token=BEARER_TOKEN
    )
    # v1.1 medya yüklemek için
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    api_v1 = tweepy.API(auth)
    return client, api_v1

def post_with_image(text, image_path):
    client, api_v1 = get_clients()
    media_ids = None
    if image_path and os.path.exists(image_path):
        media = api_v1.media_upload(image_path)
        # Tweepy Client v2 iki farklı imla destekleyebilir; ikisini de deneriz:
        try:
            client.create_tweet(text=text, media={"media_ids": [media.media_id]})
            return
        except Exception:
            pass
        client.create_tweet(text=text, media_ids=[media.media_id])
    else:
        client.create_tweet(text=text)

def main():
    rates = get_rates()
    text = build_text(rates)
    # güvenli uzunluk
    if len(text) > 270:
        text = text[:267].rstrip() + "..."
    post_with_image(text, FX_IMAGE_PATH)

if __name__ == "__main__":
    main()
