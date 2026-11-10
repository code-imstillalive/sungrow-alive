"""Draw brand/icon.png and brand/icon@2x.png: an orange sun with a heartbeat line.

Run: python tools/make_icon.py custom_components/sungrow_sh_t/brand
"""
import math, sys
from PIL import Image, ImageDraw, ImageFilter
OUT = sys.argv[1]
N = 1024                               # draw large, scale down for clean edges
ORANGE = (247, 147, 30, 255)           # warm orange
DEEP = (226, 104, 18, 255)             # deeper orange for the pulse
def icon():
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy, r = 512, 420, 210
    # rays: rounded strokes around the sun
    for k in range(12):
        a = math.pi * 2 * k / 12
        r1, r2 = r + 55, r + 140
        x1, y1 = cx + r1 * math.cos(a), cy + r1 * math.sin(a)
        x2, y2 = cx + r2 * math.cos(a), cy + r2 * math.sin(a)
        d.line([(x1, y1), (x2, y2)], fill=ORANGE, width=46)
        for (x, y) in ((x1, y1), (x2, y2)):
            d.ellipse([x - 23, y - 23, x + 23, y + 23], fill=ORANGE)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ORANGE)
    # heartbeat line across the lower sun, in a deeper orange with a white edge
    pts = [(70, 700), (330, 700), (400, 560), (480, 860), (570, 470), (640, 700), (954, 700)]
    for w, col in ((92, (255, 255, 255, 255)), (54, DEEP)):
        d.line(pts, fill=col, width=w, joint="curve")
        for (x, y) in (pts[0], pts[-1]):
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=col)
    return img
art = icon()
# soft drop shadow like Nimbus's icon
shadow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
alpha = art.split()[3].point(lambda v: int(v * 0.35))
shadow.putalpha(alpha)
shadow = shadow.filter(ImageFilter.GaussianBlur(14))
canvas = Image.new("RGBA", (N, N), (0, 0, 0, 0))
canvas.alpha_composite(shadow, (10, 16))
canvas.alpha_composite(art)
canvas.resize((512, 512), Image.LANCZOS).save(f"{OUT}/icon@2x.png")
canvas.resize((256, 256), Image.LANCZOS).save(f"{OUT}/icon.png")
print("ok")
# trim to the artwork (brands: "the minimum amount of transparent spacing"), then square it
bbox = canvas.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
art = canvas.crop(bbox)
side = max(art.size)
sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
sq.alpha_composite(art, ((side - art.size[0]) // 2, (side - art.size[1]) // 2))
sq.resize((512, 512), Image.LANCZOS).save(f"{OUT}/icon@2x.png")
sq.resize((256, 256), Image.LANCZOS).save(f"{OUT}/icon.png")
print("trimmed", bbox, "->", side)
