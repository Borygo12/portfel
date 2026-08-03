"""Generuje awatar/ikonę NewsTrader (icon.ico) — bot z motywem tradingu."""
import math
import os

from PIL import Image, ImageDraw

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# --- tło: zaokrąglony kwadrat z pionowym gradientem navy -> granatowy ---
top = (22, 30, 52)
bot = (9, 12, 20)
bg = Image.new("RGB", (S, S))
bd = ImageDraw.Draw(bg)
for y in range(S):
    t = y / S
    bd.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S, S], radius=112, fill=255)
img.paste(bg, (0, 0), mask)

# subtelna poświata w rogu
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse([S*0.45, -S*0.2, S*1.25, S*0.55], fill=(91, 140, 255, 46))
img.alpha_composite(Image.composite(glow, Image.new("RGBA", (S, S), (0,0,0,0)),
                                    mask.point(lambda p: p)))

ACC = (91, 140, 255)
GRN = (47, 212, 138)

# --- głowa bota ---
hx0, hy0, hx1, hy1 = 128, 168, 384, 372
d.rounded_rectangle([hx0, hy0, hx1, hy1], radius=54,
                    fill=(28, 38, 62), outline=ACC, width=7)
# antena
d.line([(256, 168), (256, 120)], fill=ACC, width=8)
d.ellipse([240, 96, 272, 128], fill=GRN)
# oczy (świecące)
for cx in (196, 316):
    d.ellipse([cx-30, 232-30, cx+30, 232+30], fill=(12, 18, 30))
    d.ellipse([cx-19, 232-19, cx+19, 232+19], fill=ACC)
    d.ellipse([cx-8, 232-12, cx+6, 232+2], fill=(210, 226, 255))
# uśmiech
d.arc([206, 250, 306, 336], start=15, end=165, fill=GRN, width=9)

# --- linia trendu (świeca/wykres) u dołu ---
pts = [(150, 430), (200, 402), (250, 418), (300, 372), (352, 352), (392, 320)]
d.line(pts, fill=GRN, width=10, joint="curve")
d.polygon([(392, 320), (372, 326), (386, 342)], fill=GRN)  # grot strzałki

os.makedirs(os.path.dirname(os.path.abspath(__file__)), exist_ok=True)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out.replace(".ico", ".png"))
print("zapisano:", out)
