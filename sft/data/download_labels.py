"""Download cleaned labels from the Zenodo replication package.

Source: "Too Noisy To Learn" (Liu et al., 2025, arXiv:2502.02757)
URL: https://zenodo.org/records/13150598
File: RQ1_Noisy_Classification.zip (27 MB)

Usage:
    python -m sft.data.download_labels [--out-dir data/labels]
"""

import argparse
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm


DEFAULT_OUT = Path("data/labels")

ZENODO_URL = "https://zenodo.org/records/13150598/files/RQ1_Noisy_Classification.zip"
ZIP_FILENAME = "RQ1_Noisy_Classification.zip"


def download_labels(out_dir: Path = DEFAULT_OUT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / ZIP_FILENAME

    # Check if already extracted
    existing = list(out_dir.rglob("*.csv")) + list(out_dir.rglob("*.jsonl")) + list(out_dir.rglob("*.txt"))
    if existing:
        print(f"Labels already present ({len(existing)} files in {out_dir})")
        for f in existing[:10]:
            print(f"  {f.relative_to(out_dir)}")
        return

    # Download
    if not zip_path.exists():
        print(f"Downloading {ZIP_FILENAME} from Zenodo (~27 MB)...")
        resp = requests.get(ZENODO_URL, stream=True, timeout=120)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        with open(zip_path, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True) as pbar:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))

    # Extract
    print(f"Extracting {zip_path}...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)

    # List contents
    print("Extracted contents:")
    for f in sorted(out_dir.rglob("*")):
        if f.is_file():
            size = f.stat().st_size
            print(f"  {f.relative_to(out_dir)} ({size:,} bytes)")

    zip_path.unlink()
    print("Done (zip removed).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Zenodo cleaned labels")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    download_labels(args.out_dir)
