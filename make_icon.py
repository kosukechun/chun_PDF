from pathlib import Path
from PIL import Image, ImageDraw

assets = Path(__file__).parent / "assets"
target = assets / "app_icon.png"
if not target.exists():
    image = Image.new("RGBA", (256, 256))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((5, 5, 250, 250), radius=50, fill="#17676a")
    d.polygon([(65, 42), (152, 42), (193, 83), (193, 215), (65, 215)], fill="#f5f6ef")
    d.polygon([(152, 42), (152, 83), (193, 83)], fill="#9bc9bf")
    for y, width in [(111, 76), (138, 91), (165, 55)]:
        d.rounded_rectangle((82, y, 82 + width, y + 7), radius=3, fill="#17676a")
    image.save(target)
Image.open(target).convert("RGBA").save(
    assets / "app.ico", sizes=[(i, i) for i in [16, 24, 32, 48, 64, 128, 256]]
)
