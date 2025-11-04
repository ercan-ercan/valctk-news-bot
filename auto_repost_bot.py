# auto_repost_bot.py
# 39Dakika: RSS -> (rewrite) -> X paylaşım (opsiyonel görsel)
# Gereken pip: tweepy, requests, beautifulsoup4, lxml, rapidfuzz, unidecode

import os, json, time, re, tempfile
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from lxml import etree
import tweepy
from unidecode import unidecode

# ------------------ Ayarlar / Env ------------------

DRY_MODE = os.getenv("DRY_MODE", "false").lower() in ("1","true","yes")
ATTACH_OG_IMAGE = os.getenv("ATTACH_OG_IMAGE", "true").lower() in ("1","true","yes")

TW_API_KEY     = os.getenv("TW_API_KEY")
TW_API_SECRET  = os.getenv("TW_API_SECRET")
TW_ACCESS_TOKEN = os.getenv("TW_ACCESS_TOKEN")
TW_ACCESS_SECRET= os.getenv("TW_ACCESS_SECRET")

RSS_FILE   = "rss_sources.txt"   # satır başına 1 RSS URL
STATE_FILE = "state.json"        # {"posted": ["url1", "url2", ...]}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; 39DakikaBot/1.0; +https://twitter.com/39Dakika)"
}
TIMEOUT = 15

# ------------------ Yardımcılar ------------------

def load_state() -> Dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"posted": []}

def save_state(state: Dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

def read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
        return lines
    except FileNotFoundError:
        return []

def shorten_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def ensure_period(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    if s[-1] not in ".!?":
        return s + "."
    return s

def sentence_case_tr(s: str) -> str:
    s = shorten_whitespace(s)
    if not s:
        return s
    # İlk harfi büyüt (Türkçe karakterleri koruyarak)
    return s[0].upper() + s[1:]

def dedup_list_keep_order(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

# ------------------ Twitter Clients ------------------

def get_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=TW_API_KEY,
        consumer_secret=TW_API_SECRET,
        access_token=TW_ACCESS_TOKEN,
        access_token_secret=TW_ACCESS_SECRET,
        wait_on_rate_limit=True,
    )

def get_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(TW_API_KEY, TW_API_SECRET, TW_ACCESS_TOKEN, TW_ACCESS_SECRET)
    return tweepy.API(auth, wait_on_rate_limit=True)

# ------------------ RSS Okuma ------------------

def fetch(url: str) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200 and r.content:
            return r
    except Exception:
        pass
    return None

def parse_rss_items(xml_bytes: bytes) -> List[Dict]:
    """
    Basit RSS/Atom parser (feedparser’sız).
    Dönen her item: {"title": ..., "link": ..., "summary": ...}
    """
    items: List[Dict] = []
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return items

    ns = root.nsmap or {}
    # RSS (item) veya Atom (entry) desteği
    rss_items = root.findall(".//item")
    atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if rss_items:
        for it in rss_items:
            title = "".join(it.findtext("title") or "").strip()
            link  = (it.findtext("link") or "").strip()
            desc  = "".join(it.findtext("description") or "").strip()
            if not link:
                # bazı RSS’ler linki <guid>’da taşır
                link = (it.findtext("guid") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "summary": desc})
    elif atom_items:
        for it in atom_items:
            title = "".join(it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = it.find("{http://www.w3.org/2005/Atom}link")
            link = ""
            if link_el is not None:
                link = link_el.attrib.get("href", "").strip()
            summary = "".join(it.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "summary": summary})
    return items

def gather_candidates() -> List[Dict]:
    urls = read_lines(RSS_FILE)
    all_items: List[Dict] = []
    for u in urls:
        r = fetch(u)
        if not r: 
            continue
        items = parse_rss_items(r.content)
        for it in items:
            # bazı linkler takip etmeye değmez (kısaltıcılar vs.)
            if it.get("link", "").startswith(("javascript:", "mailto:")):
                continue
            all_items.append(it)
    # Aynı linkleri ayıkla (ilk gelen kazansın)
    uniq = []
    seen = set()
    for it in all_items:
        lk = it.get("link", "")
        if lk and lk not in seen:
            seen.add(lk)
            uniq.append(it)
    return uniq

# ------------------ Rewrite (Türkçe) ------------------

PUNCT_FIX = re.compile(r"\s+([,.!?;:])")
SPACE_FIX = re.compile(r"\s+")

def clean_text(s: str) -> str:
    s = BeautifulSoup(s or "", "lxml").get_text(" ")
    s = SPACE_FIX.sub(" ", s).strip()
    s = PUNCT_FIX.sub(r"\1", s)
    return s

def smart_join_sentences(parts: List[str]) -> str:
    parts = [ensure_period(p.strip()) for p in parts if p and p.strip()]
    text = " ".join(parts)
    # Fazla boşluk/punktüasyon düzelt
    text = clean_text(text)
    # İlk harfi büyüt
    if text:
        text = sentence_case_tr(text)
    return text

def rewrite_tr(title: str, summary: str) -> str:
    """
    Basit ama kaliteli: başlığı doğal dille, özetini ikinci cümle gibi.
    Fazla tekrarları ve gereksiz uzunluğu kırpar.
    """
    t = clean_text(title)
    s = clean_text(summary)

    # Başlıktaki kırpılabilir süsler
    t = re.sub(r"^\s*(SON DAKİKA[:\-–]?)\s*", "", t, flags=re.I)
    t = re.sub(r"\s*\|\s*.+$", "", t)  # site adı vb.

    # Özet çok başlığı tekrar ediyorsa özetini at
    if s and unidecode(s.lower()).startswith(unidecode(t.lower())[:60]):
        s = ""

    # Başlığı cümle yap
    t = ensure_period(t)
    # Özet varsa tek-iki cümleye indir
    if s:
        # parantez içi/URL kırp
        s = re.sub(r"\(.*?\)", "", s)
        s = re.sub(r"http\S+", "", s)
        # çok uzunsa ilk cümlecik
        parts = re.split(r"(?<=[.!?])\s+", s)
        s = parts[0].strip()
        s = ensure_period(s)

    text = smart_join_sentences([t, s])
    # Çok uzunsa X limitine yaklaş (280)
    if len(text) > 260:
        text = text[:257].rstrip() + "..."
    return text

# ------------------ OG Görsel ------------------

def extract_og_image(url: str) -> Optional[str]:
    r = fetch(url)
    if not r:
        return None
    try:
        soup = BeautifulSoup(r.text, "lxml")
        og = soup.find("meta", attrs={"property": "og:image"}) or \
             soup.find("meta", attrs={"name": "og:image"})
        if og and og.get("content"):
            img = og["content"].strip()
            # bazı siteler relatif döner
            if img.startswith("//"):
                img = "https:" + img
            return img
    except Exception:
        pass
    return None

def download_temp(url: str) -> Optional[str]:
    try:
        rr = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if rr.status_code == 200 and rr.content:
            fd, path = tempfile.mkstemp(prefix="img_", suffix=".jpg")
            os.close(fd)
            with open(path, "wb") as f:
                f.write(rr.content)
            return path
    except Exception:
        pass
    return None

def try_upload_media(image_url: str) -> Optional[str]:
    try:
        path = download_temp(image_url)
        if not path:
            return None
        api = get_api_v1()
        up = api.media_upload(path)
        try:
            os.unlink(path)
        except Exception:
            pass
        return getattr(up, "media_id_string", None) or str(getattr(up, "media_id", ""))
    except Exception as e:
        print("[WARN] Medya yüklenemedi:", e)
        return None

# ------------------ Tweet At ------------------

def post_tweet(text: str, image_url: Optional[str]) -> Optional[str]:
    if DRY_MODE:
        print("[DRY] Tweet atılacak (görsel={}):\n{}".format(bool(image_url), text))
        return "DRY"

    client = get_client_v2()

    media_ids = None
    if ATTACH_OG_IMAGE and image_url:
        mid = try_upload_media(image_url)
        if mid:
            media_ids = [mid]
        else:
            print("[WARN] Görsel eklenemedi, metinle devam.")

    try:
        if media_ids:
            resp = client.create_tweet(text=text, media_ids=media_ids)
        else:
            resp = client.create_tweet(text=text)
        tid = getattr(resp, "data", {}).get("id")
        print(f"[OK] Tweet gönderildi. ID: {tid}")
        return tid
    except Exception as e:
        print("Error:", e)
        return None

# ------------------ Ana Akış ------------------

def choose_unposted(candidates: List[Dict], posted: List[str]) -> Optional[Dict]:
    for it in candidates:
        link = it.get("link", "")
        if link and link not in posted:
            return it
    return None

def main():
    state = load_state()
    posted = state.get("posted", [])

    candidates = gather_candidates()
    if not candidates:
        print("[INFO] RSS boş ya da ulaşılamıyor.")
        return

    item = choose_unposted(candidates, posted)
    if not item:
        print("[INFO] Yeni içerik yok.")
        return

    title = item.get("title") or ""
    summary = item.get("summary") or ""
    link = item.get("link") or ""

    text = rewrite_tr(title, summary)
    # Link istemiyorsun demiştin; tweet metninde link yok.
    # (İleride istersen sonuna kısaltılmış link ekleriz.)

    image_url = extract_og_image(link)

    tid = post_tweet(text, image_url)

    # Başarılıysa state’e ekle
    if tid:
        posted.append(link)
        state["posted"] = dedup_list_keep_order(posted)[-1000:]  # şişmesin
        save_state(state)

if __name__ == "__main__":
    # hızlı env test
    miss = [k for k in ("TW_API_KEY","TW_API_SECRET","TW_ACCESS_TOKEN","TW_ACCESS_SECRET") if not os.getenv(k)]
    if miss:
        print("[WARN] Eksik env:", miss)
    main()
