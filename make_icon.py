from pathlib import Path
try:
    from PIL import Image
except ImportError:
    raise SystemExit("Install Pillow: pip install Pillow")

src = Path(r"C:\Users\thega\.cursor\projects\d-Code-Serenity\assets\c__Users_thega_AppData_Roaming_Cursor_User_workspaceStorage_05c72d95950d5319d4b2d3fad248cc98_images_image-e8a7030e-e15b-4558-8693-c7977547f318.png")
out = Path(__file__).resolve().parent / "icon.ico"
if not src.exists():
    raise SystemExit(f"Source image not found: {src}")

img = Image.open(src).convert("RGBA")
w, h = img.size
size = min(w, h)
left = (w - size) // 2
top = (h - size) // 2
cropped = img.crop((left, top, left + size, top + size))
base = cropped.resize((256, 256), Image.Resampling.LANCZOS)
base.save(out, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
print("Created", out)
logo_out = Path(__file__).resolve().parent / "logo.png"
cropped.resize((512, 512), Image.Resampling.LANCZOS).save(logo_out, format="PNG")
print("Created", logo_out)
