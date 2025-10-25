import os
import io
import requests
from PIL import Image, ImageDraw, ImageFont
import tweepy
from datetime import datetime

# --- Güvenli font yükleyici ---
import PIL

def load_font(size: int):
    candidates = [
        os.getenv("FONT_PATH"),
        "DejaVuSans.ttf",
        os.path.join(os.path.dirname(PIL.__file__), "fonts", "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if not p:
            continue
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

# --- Twitter API ayarları ---
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")

auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
api = tweepy.API(auth)

# --- TCMB'den döviz ve altın verisi çek ---
def get_rates():
    try:
        url = "https://api.genelpara.com/embed/para-birimleri.json"
        r = requests.get(url, timeout=10)
        data = r.json()

        usd = float(data["USD"]["satis"].replace(",", "."))
        eur = float(data["EUR"]["satis"].replace(",", "."))
        gram = float(data["GA"]["satis"].replace(",", "."))
        tam = float(gram * 7.216)

        return {
            "USD": usd,
            "EUR": eur,
            "GA": gram,
            "TA": tam,
            "USDchg": float(data["USD"]["degisim"].replace(",", ".")),
            "EURchg": float(data["EUR"]["degisim"].replace(",", ".")),
            "GAchg": float(data["GA"]["degisim"].replace(",", ".")),
        }
    except Exception as e:
        print("Veri alınamadı:", e)
        return None

# --- Görsel oluştur ---
def create_image(rates):
    img = Image.new("RGB", (900, 500), (10, 10, 15))
    draw = ImageDraw.Draw(img)

    title_font = load_font(44)
    label_font = load_font(34)
    value_font = load_font(38)

    y = 80
    draw.text((320, 20), "Kapanış | Döviz & Altın", font=title_font, fill=(255, 255, 255))

    def draw_line(label, value, change):
        nonlocal y
        color = (0, 255, 0) if change >= 0 else (255, 70, 70)
        arrow = "▲" if change >= 0 else "▼"
        draw.text((100, y), f"{label}:", font=label_font, fill=(230, 230, 230))
        draw.text((350, y), f"{value:,.2f}", font=value_font, fill=(255, 255, 255))
        draw.text((650, y), f"{arrow}{abs(change):.2f}%", font=value_font, fill=color)
        y += 80

    draw_line("Dolar", rates["USD"], rates["USDchg"])
    draw_line("Euro", rates["EUR"], rates["EURchg"])
    draw_line("Gram Altın", rates["GA"], rates["GAchg"])
    draw_line("Tam Altın", rates["TA"], rates["GAchg"])

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out

# --- Tweet at ---
def tweet_fx():
    rates = get_rates()
    if not rates:
        print("⚠️ Veriler alınamadı, tweet atlanıyor.")
        return

    caption = (
        f"Kapanış | Döviz & Altın\n\n"
        f"Dolar:\t{rates['USD']:.2f}\t({('▲' if rates['USDchg']>=0 else '▼')}{abs(rates['USDchg']):.2f}%)\n"
        f"Euro:\t{rates['EUR']:.2f}\t({('▲' if rates['EURchg']>=0 else '▼')}{abs(rates['EURchg']):.2f}%)\n"
        f"Gram Altın:\t{rates['GA']:.2f}\t({('▲' if rates['GAchg']>=0 else '▼')}{abs(rates['GAchg']):.2f}%)\n"
        f"Tam Altın:\t{rates['TA']:.2f}\t({('▲' if rates['GAchg']>=0 else '▼')}{abs(rates['GAchg']):.2f}%)"
    )

    img = create_image(rates)
    filename = "fx_card.png"
    with open(filename, "wb") as f:
        f.write(img.read())

    try:
        media = api.media_upload(filename)
        api.update_status(status=caption, media_ids=[media.media_id])
        print("✅ Tweet atıldı.")
    except Exception as e:
        print("Tweet gönderilemedi:", e)

if __name__ == "__main__":
    tweet_fx()
