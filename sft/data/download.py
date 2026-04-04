"""Download the Microsoft CodeReviewer Comment Generation dataset from Zenodo.

Source: https://zenodo.org/records/6900648
File: Comment_Generation.zip (846 MB)

Usage:
    python -m sft.data.download [--out-dir data/raw]
"""

import argparse
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm


DEFAULT_OUT = Path("data/raw")

ZENODO_URL = "https://zenodo.org/records/6900648/files/Comment_Generation.zip"
ZIP_FILENAME = "Comment_Generation.zip"


def download(out_dir: Path = DEFAULT_OUT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / ZIP_FILENAME

    # Check if already extracted
    extracted = list(out_dir.glob("Comment_Generation/**/*"))
    if extracted:
        print(f"Already extracted ({len(extracted)} files in {out_dir / 'Comment_Generation'})")
        return

    # Download
    if not zip_path.exists():
        print(f"Downloading {ZIP_FILENAME} from Zenodo (~846 MB)...")
        print(f"  URL: {ZENODO_URL}")
        resp = requests.get(ZENODO_URL, stream=True, timeout=300)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        with open(zip_path, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True) as pbar:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))
        print(f"  Downloaded to {zip_path}")

    # Extract
    print(f"Extracting {zip_path}...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)

    # List what we got
    for f in sorted(out_dir.glob("Comment_Generation/**/*")):
        if f.is_file():
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.relative_to(out_dir)} ({size_mb:.1f} MB)")

    # Clean up zip
    zip_path.unlink()
    print("Done (zip removed to save space).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download CodeReviewer dataset")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    download(args.out_dir)
