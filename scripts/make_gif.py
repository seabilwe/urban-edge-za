"""Assemble the Temporal Controller frames (outputs/animation/frame0000.png ...) into an animated GIF with a year label.
    python scripts/make_gif.py <frames folder> <output.gif> <fonts folder>"""
import glob, sys
from PIL import Image, ImageDraw, ImageFont

src, out = sys.argv[1], sys.argv[2]
fonts = sys.argv[3]
frames = sorted(glob.glob(f"{src}/frame*.png"))[:10]
years = list(range(1975, 2025, 5))
imgs = []
for f, y in zip(frames, years):
    im = Image.open(f).convert("RGB"); d = ImageDraw.Draw(im)
    big = ImageFont.truetype(f"{fonts}/DMSerifDisplay-Regular.ttf", 54)
    small = ImageFont.truetype(f"{fonts}/DMSans-Regular.ttf", 17)
    d.text((28, 22), str(y), font=big, fill="#7A4B26")
    d.text((30, 86), "Gauteng's built-up land" + ("  (satellite year)" if y in (1975, 1990, 2000) else "  (GHSL estimate)"), font=small, fill="#4E5C58")
    d.text((30, im.height - 34), "Seabilwe Tilodi · GHSL GHS-BUILT-S R2023A (European Commission JRC)", font=small, fill="#4E5C58")
    imgs.append(im.quantize(colors=64, method=Image.Quantize.MEDIANCUT))
durations = [1400] + [900] * (len(imgs) - 2) + [2600]
imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)
print(out, len(imgs))
