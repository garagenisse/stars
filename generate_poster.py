import random
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from pathlib import Path
import json


class Mulberry32:
    def __init__(self, seed):
        self.state = seed & 0xFFFFFFFF

    def random(self):
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.state
        t = (t ^ (t >> 15)) * (t | 1)
        t &= 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    def randint(self, low, high):
        return int(self.random() * (high - low + 1)) + low

    def shuffle(self, arr):
        for i in range(len(arr) - 1, 0, -1):
            j = self.randint(0, i)
            arr[i], arr[j] = arr[j], arr[i]

# Satt SEED till ett specifikt tal for att aterskapa en tidigare bild, t.ex. SEED = 12345
# Eller lat den vara None for ett nytt slumpmassigt resultat varje gang
SEED = None

if SEED is None:
    SEED = random.randint(0, 999999)
print(f"Seed: {SEED}  (satt SEED = {SEED} i scriptet for att aterskapa denna bild)")
rng = Mulberry32(SEED)

CANVAS_W = 610
CANVAS_H = 406
IMG_SIZE = 305  # originalbildernas storlek

img_dir = Path("img")
image_files = sorted(img_dir.glob("star_layer_*.png"))

# Ladda alla bilder och extrahera vita pixlar (stjarnor)
print(f"Laddar {len(image_files)} bilder...")
images = []
for i, img_path in enumerate(image_files, 1):
    arr = np.array(Image.open(img_path).convert("RGB"))
    brightness = np.mean(arr, axis=2)
    mask = brightness > 200
    ys, xs = np.where(mask)
    star_pixels = list(zip(xs.tolist(), ys.tolist()))  # lista av (x, y)

    # Rakna ut hur mycket marginal (tomrum) som finns till varje kant
    if star_pixels:
        min_x = min(sx for sx, sy in star_pixels)
        min_y = min(sy for sx, sy in star_pixels)
        max_x = max(sx for sx, sy in star_pixels)
        max_y = max(sy for sx, sy in star_pixels)
        margin = {"left": min_x, "top": min_y,
                  "right": IMG_SIZE - 1 - max_x, "bottom": IMG_SIZE - 1 - max_y}
    else:
        margin = {"left": 0, "top": 0, "right": 0, "bottom": 0}

    images.append({"number": i, "stars": star_pixels, "margin": margin})
    print(f"  Bild {i}: {len(star_pixels)} stjarnpixlar  marginaler L{margin['left']} T{margin['top']} R{margin['right']} B{margin['bottom']}")

layers_export = {
    "canvas": {
        "width": CANVAS_W,
        "height": CANVAS_H,
        "img_size": IMG_SIZE,
        "min_dist": 8,
        "edge_margin": 20,
        "num_fillers": 30,
        "filler_min_dist": 40,
        "filler_edge_margin": 20,
    },
    "layers": [
        {
            "number": img["number"],
            "margin": img["margin"],
            "stars": img["stars"],
        }
        for img in images
    ],
}
Path("star_layers.json").write_text(json.dumps(layers_export, ensure_ascii=False), encoding="utf-8")
print("Sparad: star_layers.json")

MIN_DIST = 8  # minsta avstånd i pixlar mellan stjarnor
EDGE_MARGIN = 20  # minsta avstånd fran canvaskanterna for konstellationsstjarnor

# Bool-canvas som haller koll pa vilka pixlar ar upptagna (inkl. buffer-zon)
occupied = np.zeros((CANVAS_H, CANVAS_W), dtype=bool)

# Forberakna en cirkelform av buffer-zonen
buf = MIN_DIST
ys_buf, xs_buf = np.where(
    (np.arange(-buf, buf+1)[:, None]**2 + np.arange(-buf, buf+1)[None, :]**2) <= buf**2
)
ys_buf -= buf
xs_buf -= buf

def mark_occupied(px, py):
    """Markera en stjarna och bufferzonen runt den som upptagen."""
    for dy, dx in zip(ys_buf, xs_buf):
        ny, nx = py + dy, px + dx
        if 0 <= ny < CANVAS_H and 0 <= nx < CANVAS_W:
            occupied[ny, nx] = True

order = list(range(len(images)))
rng.shuffle(order)

placed_images = []
for idx in order:
    img = images[idx]
    # Anvand marginalen for att veta exakt hur mycket bilden kan skjutas ut
    # utan att nagra stjarnor hamnar utanfor canvas
    m = img["margin"]
    dx_min = -m["left"] + EDGE_MARGIN
    dx_max = CANVAS_W - IMG_SIZE + m["right"] - EDGE_MARGIN
    dy_min = -m["top"] + EDGE_MARGIN
    dy_max = CANVAS_H - IMG_SIZE + m["bottom"] - EDGE_MARGIN
    placed = False

    for attempt in range(50000):
        dx = rng.randint(dx_min, dx_max)
        dy = rng.randint(dy_min, dy_max)

        conflict = False
        for sx, sy in img["stars"]:
            if occupied[sy + dy, sx + dx]:
                conflict = True
                break

        if not conflict:
            for sx, sy in img["stars"]:
                mark_occupied(sx + dx, sy + dy)
            img["offset"] = (dx, dy)
            placed_images.append(img)
            placed = True
            print(f"  Bild {img['number']}: offset ({dx}, {dy})")
            break

    if not placed:
        print(f"  Bild {img['number']}: kunde inte placeras!")

# Vit bakgrund, rita stjarnor som svarta punkter
canvas = np.ones((CANVAS_H, CANVAS_W, 3), dtype=np.uint8) * 255

for img in placed_images:
    dx, dy = img["offset"]
    for sx, sy in img["stars"]:
        canvas[sy + dy, sx + dx] = [0, 0, 0]

# Lagg till 30 fyllnadsstjarnor (X) - slumpa positioner, godkann om minst 20px fran alla andra
NUM_FILLERS = 30
FILLER_MIN_DIST = 40
MARGIN = 20

# Samla alla befintliga stjarnkoordinater
all_stars_xy = []
for img in placed_images:
    dx, dy = img["offset"]
    for sx, sy in img["stars"]:
        all_stars_xy.append((sx + dx, sy + dy))
all_stars_xy = np.array(all_stars_xy, dtype=np.float32)

filler_stars = []
for _ in range(NUM_FILLERS):
    for attempt in range(100000):
        fx = rng.randint(MARGIN, CANVAS_W - MARGIN - 1)
        fy = rng.randint(MARGIN, CANVAS_H - MARGIN - 1)
        # Kontrollera avstand till alla befintliga + tidigare X stjarnor
        check = np.array(all_stars_xy.tolist() + filler_stars, dtype=np.float32)
        if len(check) == 0 or np.min(np.sqrt((check[:,0]-fx)**2 + (check[:,1]-fy)**2)) >= FILLER_MIN_DIST:
            filler_stars.append((fx, fy))
            canvas[fy, fx] = [0, 0, 0]
            break

print(f"Lade till {len(filler_stars)} fyllnadsstjarnor (X)")

# Rita bokstav vid varje stjarna (A=bild1, B=bild2 osv)
try:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 8)
except:
    font = ImageFont.load_default()

pil_canvas = Image.fromarray(canvas)
draw = ImageDraw.Draw(pil_canvas)
for img in placed_images:
    dx, dy = img["offset"]
    letter = chr(ord('A') + img["number"] - 1)
    for sx, sy in img["stars"]:
        draw.text((sx + dx + 2, sy + dy - 9), letter, fill=0, font=font)

# Rita X for fyllnadsstjarnor
for fx, fy in filler_stars:
    draw.text((fx + 2, fy - 9), "X", fill=0, font=font)

canvas = np.array(pil_canvas)

# Svart ram, 1 pixel bred
canvas[0, :] = [0, 0, 0]
canvas[-1, :] = [0, 0, 0]
canvas[:, 0] = [0, 0, 0]
canvas[:, -1] = [0, 0, 0]

Image.fromarray(canvas).save("stars_poster.png")

layout_export = {
    "seed": SEED,
    "rng": "mulberry32",
    "canvas": {"width": CANVAS_W, "height": CANVAS_H},
    "parameters": {
        "min_dist": MIN_DIST,
        "edge_margin": EDGE_MARGIN,
        "num_fillers": NUM_FILLERS,
        "filler_min_dist": FILLER_MIN_DIST,
        "filler_edge_margin": MARGIN,
    },
    "placed_layers": [
        {
            "number": img["number"],
            "offset": list(img["offset"]),
            "star_count": len(img["stars"]),
        }
        for img in placed_images
    ],
    "filler_stars": filler_stars,
}
Path("stars_layout.json").write_text(json.dumps(layout_export, ensure_ascii=False), encoding="utf-8")

print(f"\nSparad: stars_poster.png  ({CANVAS_W}x{CANVAS_H} px)")
print("Sparad: stars_layout.json")
print(f"{len(placed_images)}/12 bilder placerade")
