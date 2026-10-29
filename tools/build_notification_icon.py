"""Build public header derivatives; keep the push/manifest original unchanged."""
import argparse
import hashlib
from pathlib import Path
from PIL import Image, PngImagePlugin
ROOT = Path(__file__).resolve().parents[1]
SIZES = (76, 152, 304)

def build(check=False, asset="notification"):
    """Reuse the public PNG pipeline; never rewrite the source asset."""
    if asset not in {"notification", "truck"}:
        raise ValueError("Unsupported public display asset")
    sizes = SIZES if asset == "notification" else (96, 192, 384)
    source = ROOT / f"static/icons/{asset}.png"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with Image.open(source) as original:
        for size in sizes:
            target = source.with_name(f"{asset}-display-{size}.png")
            if check:
                with Image.open(target) as derived:
                    assert derived.size == (size, size), target
                    assert derived.info.get("SourceSHA256") == digest, target
                    derived.verify()
            else:
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text("SourceSHA256", digest)
                original.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS).save(
                    target, pnginfo=metadata, optimize=True)
            print(f"{target.name}: {target.stat().st_size} bytes")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--asset", choices=("notification", "truck"), default="notification")
    args = parser.parse_args()
    build(args.check, args.asset)
