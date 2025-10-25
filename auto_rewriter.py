#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_rewriter.py - Free plan uyumlu, no-wait versiyon
- Rate limit gelirse hemen çıkar, beklemez.
- Tek hesap / az istekle güvenli çalışır.
"""

import os, json, re, sys, time
import argparse
from typing import List, Dict, Optional
from dotenv import load_dotenv
import tweepy

STATE_PATH = "state.json"
SOURCES_PATH = "sources.txt"
MAX_TWEET_LEN = 280

def load_env():
    load_dotenv()
    need = ["API_KEY","API_SECRET","ACCESS_TOKEN","ACCESS_TOKEN_SECRET","BEARER_TOKEN"]
    vals = {k: os.getenv(k) for k in need}
    missing = [k for k,v in vals.items() if not v]
    if missing:
        raise RuntimeError(f".env eksik: {', '.join(missing)}")
    return vals

def get_client(vals):
    return tweepy.Client(
        consumer_key=vals["API_KEY"],
        consumer_secret=vals["API_SECRET"],
        access_token=vals["ACCESS_TOKEN"],
        access_token_secret=vals["ACCESS_TOKEN_SECRET"],
        bearer_token=vals["BEARER_TOKEN"],
        wait_on_rate_limit=False
    )

def load_sources() -> List[str]:
    if not os.path.exists(SOURCES_PATH):
        raise RuntimeError(f"{SOURCES_PATH} yok.")
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        lines = [re.sub(r"^@","",x.strip()) for x in f if x.strip()]
    if not lines:
        raise RuntimeError(f"{SOURCES_PATH} boş.")
    return lines

def load_state() -> Dict[str, str]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: Dict[str,str]) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_turkish_text(text: str, lang_hint: Optional[str]) -> bool:
    if lang_hint and lang_hint.lower() == "tr":
        return True
    if re.search(r"[çğıöşüİ]", text): return True
    common = [" ve ", " ile ", "bugün", "yarın", "TRT", "maçı", "Türkiye", "son dakika", "güncelleme"]
    return any(w in text.lower() for w in common)

def clean_text(text: str) -> str:
    text = re.sub(r"^RT\s+@", "@", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+#\S+", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text

def simple_paraphrase(text: str) -> str:
    t = text
    swaps = [
        (r"\bson dakika\b", "gelişme"),
        (r"\bbugün\b", "bugün itibarıyla"),
        (r"\bduyurdu\b", "bildirdi"),
        (r"\bmaçı\b", "karşılaşması"),
        (r"\byayınlanacak\b", "ekrana gelecek"),
        (r"\byayınlanıyor\b", "ekrana geliyor"),
        (r"\bcanlı\b", "canlı olarak"),
    ]
    for pat, rep in swaps:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    if len(t) < 40 and not t.endswith(("!","?",".")):
        t += "."
    return re.sub(r"\s{2,}", " ", t).strip()

def clamp_280(text: str) -> str:
    return text if len(text) <= MAX_TWEET_LEN else text[: MAX_TWEET_LEN - 1] + "…"

def fetch_new_from_user(client, username: str, since_id: Optional[str], max_results: int):
    u = client.get_user(username=username)
    if not u.data:
        return []
    uid = u.data.id
    kwargs = {
        "id": uid,
        "exclude": ["retweets","replies"],
        "tweet_fields": ["lang","created_at","public_metrics"],
        "max_results": max(5, min(max_results, 100)),
    }
    if since_id:
        kwargs["since_id"] = since_id
    try:
        resp = client.get_users_tweets(**kwargs)
    except tweepy.TooManyRequests:
        print(f"[{username}] Rate limit. Çıkılıyor (no-wait).")
        sys.exit(0)
    if not resp or not resp.data:
        return []
    items = list(resp.data)
    items.sort(key=lambda x: int(x.id))
    out = []
    for tw in items:
        out.append({
            "id": str(tw.id),
            "text": tw.text,
            "lang": getattr(tw, "lang", None),
            "created_at": str(getattr(tw, "created_at", "")),
            "username": username
        })
    return out

def build_output(original: str, username: str, credit: bool) -> str:
    base = clean_text(original)
    para = simple_paraphrase(base)
    out = f"{para} — Kaynak: @{username}" if credit else para
    return clamp_280(out)

def main():
    ap = argparse.ArgumentParser(description="Auto rewriter bot (Free plan safe mode)")
    ap.add_argument("--post", action="store_true", help="Gerçekten gönder")
    ap.add_argument("--limit", type=int, default=1, help="Kaynak başına kaç tweet işlensin")
    ap.add_argument("--credit", action="store_true", help="Sonuna Kaynak: @kullanici ekle")
    ap.add_argument("--only", type=str, help="Sadece bu kullanıcı(lar) (virgülle ayır)")
    ap.add_argument("--cooldown", type=int, default=900, help="Kaynaklar arası bekleme (sn)")
    ap.add_argument("--max-results", type=int, default=1, help="API çağrısında getirilecek tweet sayısı")
    args = ap.parse_args()

    vals = load_env()
    client = get_client(vals)
    me = client.get_me()
    me_user = me.data.username if me and me.data else "me"
    print(f"Giriş (v2): @{me_user}")

    sources = load_sources()
    if args.only:
        wanted = [re.sub(r"^@","",s.strip()) for s in args.only.split(",") if s.strip()]
        sources = [s for s in sources if s in wanted]
        if not sources:
            print("Seçtiğin --only listesi sources.txt ile eşleşmiyor.")
            sys.exit(0)

    state = load_state()
    total_posted = 0

    for idx, username in enumerate(sources, 1):
        since_id = state.get(username)
        try:
            items = fetch_new_from_user(client, username, since_id, args.max_results)
        except tweepy.TooManyRequests:
            print(f"[{username}] Rate limit. Çıkılıyor (no-wait).")
            sys.exit(0)

        if not items:
            print(f"[{username}] yeni tweet yok.")
            continue

        processed = 0
        for item in items:
            if processed >= args.limit:
                continue
            if not is_turkish_text(item["text"], item.get("lang")):
                continue

            out = build_output(item["text"], username, args.credit)

            print("\n--- KAYNAK ---------------------------------")
            print(f"@{username} | {item['created_at']} | id={item['id']}")
            print(item["text"])
            print("--- ÖNERİLEN --------------------------------")
            print(out)
            print("---------------------------------------------")

            if args.post:
                try:
                    r = client.create_tweet(text=out)
                    tid = r.data.get("id") if r and r.data else "unknown"
                    print(f"→ Gönderildi (v2). ID: {tid}")
                    total_posted += 1
                except tweepy.TooManyRequests:
                    print("→ Gönderimde rate limit. Çıkılıyor (no-wait).")
                    sys.exit(0)
                except tweepy.TweepyException as te:
                    print(f"→ Gönderim hatası: {te}")
                except Exception as e:
                    print(f"→ Hata: {e}")
            else:
                print("→ Dry-run (gönderilmedi).")

            processed += 1
            time.sleep(1.0)

        state[username] = items[-1]["id"]
        save_state(state)

    print(f"\nBitti. Toplam gönderilen: {total_posted}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nİptal edildi.")

