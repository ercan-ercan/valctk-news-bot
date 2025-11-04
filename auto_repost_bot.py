# auto_repost_bot.py
# 39Dakika: RSS -> (rewrite) -> X paylaşım (opsiyonel görsel)
# pip: tweepy, requests, beautifulsoup4, lxml, rapidfuzz, unidecode

import os, json, time, re, tempfile
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from lxml import etree
import tweepy
from unidecode import unidecode

# ------------------ Ayarlar / Env ------------------

DRY_MODE = os.getenv("DRY_MODE", "false").lower() in ("1","true","yes")
ATTACH_OG_IMAGE = os.getenv("ATTACH_OG_IMAGE", "true").lower() in ("1","true","yes")

TW_API_KEY      = os.getenv("TW_API_KEY")
TW_API_SECRET   = os.getenv("TW_API_SECRET")
TW_ACCESS_TOKEN = os.getenv("TW_ACCESS_TOKEN")
TW_ACCESS_SECRET= os.getenv("TW_ACCESS_SECRET")

RSS_FILE   = "rss_sources.txt"   # satır / RSS URL
STATE_FILE = "state.json"        # {"posted": ["url1", ...]}

HEADERS = {"User-Agent": "Mozilla/5.0 (39DakikaBot/1.0)"}
TIMEOUT = 15

# ------------------ State & IO ------------------

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
            return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    except FileNotFoundError:
        return []

def dedup_keep_order(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
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

# ------------------ HTTP / RSS ------------------

def fetch(url: str) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.ok and r.content:
            return r
    except Exception:
        pass
    return None

def parse_rss_items(xml_bytes: bytes) -> List[Dict]:
    """Basit RSS/Atom parser (feedparser yok)."""
    items: List[Dict] = []
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return items

    rss_items = root.findall(".//item")
    atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    if rss_items:
        for it in rss_items:
            title = (it.findtext("title") or "").strip()
            link  = (it.findtext("link") or "").strip() or (it.findtext("guid") or "").strip()
            desc  = (it.findtext("description") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "summary": desc})
    elif atom_items:
        for it in atom_items:
            title = (it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = it.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.attrib.get("href", "").strip() if link_el is not None else ""
            summary = (it.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "summary": summary})
    return items

def gather_candidates() -> List[Dict]:
    urls = read_lines(RSS_FILE)
    all_items: List[Dict] = []
    for u in urls:
        r = fetch(u); 
        if not r: 
            continue
        all_items.extend(parse_rss_items(r.content))
    # linke göre uniq
    seen, uniq = set(), []
    for it in all_items:
        lk = it.get("link", "")
        if lk and lk not in seen:
            seen.add(lk); uniq.append(it)
    return uniq

# ------------------ Metin Temizleme / Rewrite ------------------

SPACE_FIX = re.compile(r"\s+")
PUNCT_FIX = re.compile(r"\s+([,.!?;:])")
QUOTES = {'“':'"', '”':'"', '’':"'", '‘':"'", '«':'"', '»':'"'}

def normalize_quotes(s: str) -> str:
    for k,v in QUOTES.items(): s = s.replace(k,v)
    return s

def clean_html_text(s: str) -> str:
    s = BeautifulSoup(s or "", "lxml").get_text(" ")
    s = normalize_quotes(s)
    s = SPACE_FIX.sub(" ", s).strip()
    s = PUNCT_FIX.sub(r"\1", s)
    return s

def ensure_period(s: str) -> str:
    s = s.strip()
    if not s: return s
    return s if s[-1] in ".!?" else s + "."

def split_sentences_tr(s: str) -> List[str]:
    # kaba ama iş görür
    parts = re.split(r"(?<=[.!?])\s+", s.strip())
    return [p for p in parts if p]

def too_similar(a: str, b: str) -> bool:
    A = set(unidecode(a.lower()).split())
    B = set(unidecode(b.lower()).split())
    if not A or not B: return False
    inter = len(A & B) / max(1, len(A | B))
    return inter >= 0.6

def pick_title_speaker(title: str) -> Optional[tuple]:
    """
    'Ad Soyad: cümle' kalıbını yakala ve (speaker, quote) döndür.
    """
    if ":" not in title: 
        return None
    left, right = title.split(":", 1)
    left = left.strip()
    # 'Sayın', 'Cumhurbaşkanı', 'Bakan' gibi ünvanlar kalabilir
    if 2 <= len(left.split()) <= 6 and left[0].isupper():
        q = right.strip().strip('"').strip("'")
        return (left, q)
    return None

def rewrite_tr(title: str, summary: str) -> str:
    t = clean_html_text(title)
    s = clean_html_text(summary)

    # Başlıktan site adı/boring parçaları at
    t = re.sub(r"\s*\|\s*[^|]+$", "", t)              # sondaki site adlarını sil
    t = re.sub(r"^\s*(SON DAKİKA[:\-–]?)\s*", "", t, flags=re.I)

    # Eğer "Kişi: ..." varsa, tek cümlede net ver
    sp = pick_title_speaker(t)
    if sp:
        speaker, q = sp
        q = re.sub(r'["“”]+', "", q).strip()
        # cümleyi kesip ilk sağlam cümleyi al
        q_sent = split_sentences_tr(q)[0] if q else ""
        text = f"{speaker}: {ensure_period(q_sent or q)}"
        # özet çok benzerse ekleme
        if s and not too_similar(text, s):
            s_sent = split_sentences_tr(s)[0]
            if s_sent and not too_similar(text, s_sent):
                text = text.rstrip() + " " + ensure_period(s_sent)
        return text[:240].rstrip(". ") + "."

    # Aksi halde: başlığı cümle yap, gerekiyorsa 1 kısa destek cümlesi ekle
    title_sent = split_sentences_tr(t)[0] if t else ""
    title_sent = ensure_period(title_sent)

    add = ""
    if s and not too_similar(title_sent, s):
        s_sent = split_sentences_tr(s)[0]
        if s_sent and not too_similar(title_sent, s_sent):
            add = " " + ensure_period(s_sent)

    text = (title_sent + add).strip()
    # çok uzun olursa kısalt
    if len(text) > 240:
        text = text[:237].rstrip() + "..."
    return text

# ------------------ OG Görsel ------------------

def extract_og_image(url: str) -> Optional[str]:
    r = fetch(url)
    if not r: return None
    try:
        soup = BeautifulSoup(r.text, "lxml")
        og = soup.find("meta", attrs={"property":"og:image"}) or soup.find("meta", attrs={"name":"og:image"})
        if og and og.get("content"):
            img = og["content"].strip()
            if img.startswith("//"): img = "https:" + img
            return img
    except Exception:
        pass
    return None

def download_temp(url: str) -> Optional[str]:
    try:
        rr = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if rr.ok and rr.content:
            fd, path = tempfile.mkstemp(prefix="img_", suffix=".jpg"); os.close(fd)
            with open(path, "wb") as f: f.write(rr.content)
            return path
    except Exception:
        pass
    return None

def try_upload_media(image_url: str) -> Optional[str]:
    try:
        path = download_temp(image_url)
        if not path: return None
        api = get_api_v1()
        up = api.media_upload(path)
        try: os.unlink(path)
        except Exception: pass
        return getattr(up, "media_id_string", None) or str(getattr(up, "media_id", ""))
    except Exception as e:
        print("[WARN] Medya yüklenemedi:", e)
        return None

# ------------------ Tweet ------------------

def post_tweet(text: str, image_url: Optional[str]) -> Optional[str]:
    if DRY_MODE:
        print("[DRY] Tweet atılacak (görsel={}):\n{}".format(bool(image_url), text))
        return "DRY"

    client = get_client_v2()
    media_ids = None
    if ATTACH_OG_IMAGE and image_url:
        mid = try_upload_media(image_url)
        if mid: media_ids = [mid]
        else:   print("[WARN] Görsel eklenemedi, metinle devam.")

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

# ------------------ Akış ------------------

def choose_unposted(cands: List[Dict], posted: List[str]) -> Optional[Dict]:
    for it in cands:
        lk = it.get("link", "")
        if lk and lk not in posted:
            return it
    return None

def main():
    state = load_state()
    posted = state.get("posted", [])

    cands = gather_candidates()
    if not cands:
        print("[INFO] RSS boş."); return

    item = choose_unposted(cands, posted)
    if not item:
        print("[INFO] Yeni içerik yok."); return

    title   = item.get("title")   or ""
    summary = item.get("summary") or ""
    link    = item.get("link")    or ""

    text = rewrite_tr(title, summary)
    image_url = extract_og_image(link)

    tid = post_tweet(text, image_url)
    if tid:
        posted.append(link)
        state["posted"] = dedup_keep_order(posted)[-1000:]
        save_state(state)

if __name__ == "__main__":
    miss = [k for k in ("TW_API_KEY","TW_API_SECRET","TW_ACCESS_TOKEN","TW_ACCESS_SECRET") if not os.getenv(k)]
    if miss: print("[WARN] Eksik env:", miss)
    main()
