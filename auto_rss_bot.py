#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, re, time, json, argparse
import requests, feedparser, tweepy
from bs4 import BeautifulSoup
from dotenv import load_dotenv

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ValctkNewsBot/2.0)"}
STATE_PATH = "rss_state.json"

RSS_SOURCES_FALLBACK = [
    "http://sondakika.haber7.com/sondakika.rss",
    "https://www.sozcu.com.tr/feeds-son-dakika",
    "https://www.sabah.com.tr/rss/sondakika.xml",
    "https://feeds.bbci.co.uk/turkce/rss.xml",
    "https://www.cnnturk.com/feed/rss/all/news",
    "https://www.ntv.com.tr/rss",
    "https://www.hurriyet.com.tr/rss/anasayfa",
]

# ——— Yardımcılar ————————————————————————————————————————

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

def load_sources(path="rss_sources.txt"):
    if os.path.exists(path):
        out = []
        for line in open(path,"r",encoding="utf-8"):
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
        if out: return out
    return RSS_SOURCES_FALLBACK

def load_state():
    if not os.path.exists(STATE_PATH): return {}
    try:
        return json.load(open(STATE_PATH,"r",encoding="utf-8"))
    except Exception:
        return {}

def save_state(st):
    json.dump(st, open(STATE_PATH,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def fetch(url, timeout=12):
    return requests.get(url, headers=HEADERS, timeout=timeout)

def clean_boiler(s: str) -> str:
    if not s: return ""
    s = re.sub(r"\b(GİRİŞ|GÜNCELLEME)\s*\d{2}\.\d{2}\.\d{4}.*?$", "", s, flags=re.I)
    s = re.sub(r"\b(Bu Habere \d+ Yorum Yapılmış).*?$", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fetch_article(link: str) -> str:
    try:
        r = fetch(link)
        r.raise_for_status()
    except Exception:
        return ""
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script","style","noscript","header","footer","nav","aside"]):
        tag.decompose()
    # haber metni adayları
    selectors = [
        "article", "div.article", "div#content", "div.content",
        "div.haber_metni", "div#NewsDetail", "div.news-detail",
        "div.detail", "div#haberMetni", "section.article"
    ]
    blocks = []
    for sel in selectors:
        for c in soup.select(sel):
            txts = []
            for li in c.select("li"):
                t = li.get_text(" ", strip=True)
                if len(t) > 3: txts.append(t)
            for p in c.find_all("p"):
                t = p.get_text(" ", strip=True)
                if len(t) > 3: txts.append(t)
            if txts:
                blocks.append("\n".join(txts))
    if not blocks:
        return clean_boiler(soup.get_text(" ", strip=True))
    body = "\n".join(blocks)
    return clean_boiler(body)

def sentence_split(text: str):
    if not text: return []
    # “3. Tur” gibi kısaltmalarda cümleyi bölmemek için geçici işaret
    text = re.sub(r"(\d)\.(\s*[Tt]ur\b)", r"\1·\2", text)
    # cümlelere böl
    parts = re.split(r"(?<=[\.\!\?])\s+", text)
    out = []
    for p in parts:
        p = p.replace("·", ".").strip()
        if p:
            out.append(p)
    return out

def clamp_text(s: str, maxlen=280):
    s = s.strip()
    if len(s) <= maxlen:
        return s
    cut = s[:maxlen]
    # Son noktalama/kısa çizgi vs. den geriye yasla
    m = re.search(r"[\.!\?…—-]\s*(?!.*[\.!\?…—-])", cut)
    if m:
        return cut[:m.end()].rstrip()
    # kelime ortasında kesme
    if " " in cut:
        return cut.rsplit(" ",1)[0] + "…"
    return cut + "…"

def tidy_title(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*([.!?])\s*$", r"\1", t)
    # “..” “!!” vb sadeleştir
    t = re.sub(r"([.!?])\1+", r"\1", t)
    return t

# ——— İsim listesi/aday çıkarımı ———————————————————————————————

NAME_RE = re.compile(
    r"\b([A-ZÇĞİÖŞÜ][a-zçğıöşü\.]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü\.]+){1,2})\b"
)

STOP_SINGLE = set([
    "Bu","Şu","Bir","Ve","FED","Air","Force","One","Hazine","Bakanı","Başkanı","ABD",
    "Türkiye","İstanbul","Ankara","Resmen","Son","Dakika","Cumhurbaşkanı","Bakan"
])

def extract_candidate_names(text: str, want_min=3):
    if not text: return []
    # liste block’larını yakala
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    picks = []
    for ln in lines:
        # madde imi varsa ağırlık ver
        if ln.startswith(("-", "•", "—", "*")):
            ln = ln.lstrip("-•—* ").strip()
        for m in NAME_RE.findall(ln):
            # en az 2 kelime
            if len(m.split()) < 2:
                continue
            # tekil stopword’leri ayıkla
            parts = m.split()
            if any(w in STOP_SINGLE for w in parts):
                # örn: "Hazine Bakanı Scott Bessent" — sadece tam adı bırak
                # sonda 2-3 kelimelik tam ad varsa onu al
                tail = " ".join([w for w in parts if w not in STOP_SINGLE])
                if len(tail.split()) >= 2:
                    picks.append(tail)
                continue
            picks.append(m)
    # virgüllü paragraflardan da toparla
    for chunk in re.split(r"[;\n]", text):
        for m in NAME_RE.findall(chunk):
            if len(m.split()) >= 2 and not any(w in STOP_SINGLE for w in m.split()):
                picks.append(m)

    # normalize & uniq (orijinal sırayı koru)
    seen = set()
    uniq = []
    for x in picks:
        x = re.sub(r"\s+", " ", x).strip(" .,:;–-")
        # “Başkanı Jerome Powell” -> “Jerome Powell”
        x = re.sub(r"^(Başkanı|Bakanı|Valisi|Prof\.?|Doç\.?|Dr\.?)\s+", "", x)
        if len(x.split()) < 2: 
            continue
        key = x.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(x)

    # çok uzun değil, 2-3 kelime ideali
    cleaned = []
    for n in uniq:
        parts = n.split()
        if 2 <= len(parts) <= 3:
            cleaned.append(n)
    # çok kısaysa en azından 3-5 isim toparla
    if len(cleaned) < want_min:
        cleaned = uniq[:want_min]
    return cleaned[:10]

def summarize_with_names(title: str, body: str):
    """
    ‘5 aday belli oldu / işte isimler’ vb. ise: başlık + isim listesi (tam adlar).
    Değilse: normal kısa özet.
    """
    t = tidy_title(title)
    hay = (title + " " + body).lower()
    trigger = any(k in hay for k in [
        "5 aday", "beş aday", "aday belli oldu", "işte adaylar", "kadro açıklandı",
        "hakemleri açıklandı", "liste açıklandı"
    ])

    if trigger:
        names = extract_candidate_names(body, want_min=3)
        if names:
            lines = [t] + [f"- {n}" for n in names[:8]]
            return clamp_text("\n".join(lines), 280)

    # normal kısa özet: başlık + ilk anlamlı cümle
    sents = sentence_split(body)
    lead = ""
    for s in sents:
        if len(s) >= 40:  # çok ufak değilse
            lead = s
            break
    if not lead and sents:
        lead = sents[0]
    text = t if not lead else f"{t} {lead}"
    # tırnakları koru, fazla boşlukları düzelt
    text = re.sub(r"\s+", " ", text)
    return clamp_text(text, 280)

# ——— Filtre (gündem/ekonomi/siyaset/spor/teknoloji/sosyal) ———————————

KEYWORDS = [
    # Politika & Ekonomi
    "son dakika","seçim","cumhurbaşkanı","bakan","meclis","enflasyon","faiz",
    "dolar","euro","vergi","asgari ücret","emekli","bütçe","mb", "merkez bankası",
    # Felaket & Asayiş
    "deprem","yangın","fırtına","sel","patlama","saldırı","cinayet","gözaltı","tutuklandı",
    # Spor
    "maç","transfer","derbi","hakem","sakatlık","kadro","pfdk","tff","fenerbahçe","galatasaray","beşiktaş","trabzonspor",
    # Teknoloji
    "apple","iphone","ios","samsung","galaxy","android","yapay zeka","ai",
    # Sosyal & Trend
    "tepki çekti","gündem oldu","video","görüntü","skandal","zam",
    # Dünya / Savunma
    "gazze","israil","iran","rusya","abd","nato","ateşkes","savaş"
]

def pass_filter(title, summary):
    hay = (title + " " + (summary or "")).lower()
    return any(k in hay for k in KEYWORDS)

# ——— Akış ———————————————————————————————————————————————

def run_bot(dry: bool, max_posts: int, per_feed: int):
    client = tw_client()
    sources = load_sources()
    state = load_state()

    prepared = sent = skipped = 0

    for url in sources:
        if sent >= max_posts: break
        print(f"\n[FEED] {url}")
        st = state.get(url, {"seen": []})
        seen = set(st.get("seen", []))

        feed = feedparser.parse(url)
        entries = feed.entries if getattr(feed, "entries", None) else []

        def ent_key(e):
            dt = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
            return time.mktime(dt) if dt else 0

        entries = sorted(entries, key=ent_key)
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
            title = tidy_title((getattr(e,"title","") or "").strip())
            link  = (getattr(e,"link","") or "").strip()
            summary = (getattr(e,"summary","") or getattr(e,"subtitle","") or "").strip()

            if not title or not link:
                skipped += 1
                continue

            if not pass_filter(title, summary):
                skipped += 1
                continue

            body = fetch_article(link)
            tweet = summarize_with_names(title, body)

            print("\n--- TWEET ---")
            print(tweet)

            prepared += 1

            if dry:
                print("→ DRY-MODE (tweet edilmedi).")
            else:
                try:
                    client.create_tweet(text=tweet)
                    sent += 1
                    st.setdefault("seen", []).append(uid)
                    if len(st["seen"]) > 1000:
                        st["seen"] = st["seen"][-500:]
                except tweepy.TooManyRequests:
                    print("→ Rate limit (POST). Çıkılıyor.")
                    save_state(state); sys.exit(0)
                except tweepy.Forbidden as ex:
                    print(f"→ Hata 403: {ex}")
                except Exception as ex:
                    print(f"→ Hata: {ex}")

            # dry’de bile “görüldü”ye alalım ki aynı başlığı döndürüp durmasın
            st.setdefault("seen", []).append(uid)

            if sent >= max_posts:
                break

        state[url] = st
        save_state(state)

    print(f"\nHazırlanan: {prepared} | Gönderilen: {sent} | Atlanan: {skipped}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-posts", type=int, default=2)
    ap.add_argument("--per-feed", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_env_or_die()
    run_bot(args.dry, args.max_posts, args.per_feed)

if __name__ == "__main__":
    main()
