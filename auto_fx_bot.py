#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_fx_bot.py — Kapanış | Döviz & Altın
- Kaynaklar:
  * USDTRY & EURTRY: exchangerate.host (ücretsiz, anahtarsız)
  * XAUUSD: goldprice.org public JSON (ücretsiz, anahtarsız)
- Gram Altın = (XAUUSD / 31.1035) * USDTRY
- Tam Altın (yaklaşık) = Gram * 7.016
"""

import os, argparse, math, time
import requests
import tweepy

HEADERS = {"User-Agent": "ValctkNewsBot/1.0"}

def tr_format(x: float) -> str:
    # Türkçe sayı biçimi: binlik nokta, ondalık virgül
    s = f"{x:,.2f}"
    # s = '12,345.67' -> '12.345,67'
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def fetch_usdtry_eurtry(debug=False):
    # USD->TRY ve EUR->TRY ayrı çağrı (daha sağlam)
    u = "https://api.exchangerate.host/latest?base=USD&symbols=TRY,EUR"
    e = "https://api.exchangerate.host/latest?base=EUR&symbols=TRY,USD"
    r1 = requests.get(u, timeout=12, headers=HEADERS)
    r2 = requests.get(e, timeout=12, headers=HEADERS)

    r1.raise_for_status(); r2.raise_for_status()
    d1 = r1.json(); d2 = r2.json()

    usdtry = float(d1["rates"]["TRY"])
    eurtry = float(d2["rates"]["TRY"])
    if debug:
        print(f"DEBUG FX: USDTRY={usdtry} EURTRY={eurtry}")
    return usdtry, eurtry

def fetch_xauusd(debug=False):
    # GoldPrice.org public feed (USD/oz)
    # Örn cevap: {"items":[{"curr":"USD","xauPrice":...,"xagPrice":...}]}
    g = "https://data-asg.goldprice.org/dbXRates/USD"
    r = requests.get(g, timeout=12, headers=HEADERS)
    r.raise_for_status()
    j = r.json()
    items = j.get("items") or []
    if not items:
        raise RuntimeError("XAU feed boş")
    xauusd = float(items[0].get("xauPrice"))
    if debug:
        print(f"DEBUG XAU: XAUUSD={xauusd}")
    return xauusd

def compute_prices(debug=False):
    usdtry, eurtry = fetch_usdtry_eurtry(debug=debug)
    xauusd = fetch_xauusd(debug=debug)

    gram = (xauusd / 31.1035) * usdtry
    tam  = gram * 7.016  # yaklaşık saf altın karşılığı

    return usdtry, eurtry, gram, tam

def make_text(usdtry, eurtry, gram, tam):
    lines = []
    lines.append("Kapanış | Döviz & Altın")
    lines.append(f"Dolar:        {tr_format(usdtry)}")
    lines.append(f"Euro:         {tr_format(eurtry)}")
    lines.append(f"Gram Altın:   {tr_format(gram)}")
    lines.append(f"Tam Altın:    {tr_format(tam)}")
    return "\n".join(lines)

def tweet(text, dry=False):
    if dry:
        print("\n--- TWEET (DRY) ---")
        print(text)
        return

    API_KEY = os.getenv("API_KEY")
    API_SECRET = os.getenv("API_SECRET")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")

    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
        raise RuntimeError("Twitter kimlikleri .env içinde eksik!")

    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    api = tweepy.API(auth)
    api.update_status(text)
    print("→ Gönderildi.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    try:
        usdtry, eurtry, gram, tam = compute_prices(debug=args.debug)
        text = make_text(usdtry, eurtry, gram, tam)
        tweet(text, dry=args.dry)
    except Exception as e:
        print(f"Veri alınamadı: {e}")
        print("⚠️ Veriler alınamadı, tweet atlanıyor.")

if __name__ == "__main__":
    main()
