"""Download cleaned labels from the Zenodo replication package.

Source: "Too Noisy To Learn" (Liu et al., 2025, arXiv:2502.02757)
URL: https://zenodo.org/records/13150598

The zip contains RQ1_Noisy_Classification/ with CSV files that label each
CodeReviewer training example as "valid" or "noisy".

Usage:
    python -m sft.data.download_labels [--out-dir data/labels]

If automatic download fails (Zenodo can be slow), manually download:
    1. Go to https://zenodo.org/records/13150598
    2. Download RQ1_Noisy_Classification.zip (27 MB)
    3. Place it in data/labels/
    4. Re-run this script (it will detect and extract the zip)
"""

import argparse
import io
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm


DEFAULT_OUT = Path("data/labels")

# Direct download link from Zenodo
ZENODO_RECORD = "13150598"
ZIP_FILENAME = "RQ1_Noisy_Classification.zip"
ZENODO_URL = f"https://zenodo.org/records/{ZENODO_RECORD}/files/{ZIP_FILENAME}"


def download_labels(out_dir: Path = DEFAULT_OUT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / ZIP_FILENAME

    # Check if already extracted
    extracted_dir = out_dir / "RQ1_Noisy_Classification"
    if extracted_dir.exists() and any(extracted_dir.glob("*.csv")):
        print(f"Labels already extracted at {extracted_dir}")
        return

    # Check if zip already downloaded (manual or previous attempt)
    if not zip_path.exists():
        print(f"Downloading {ZIP_FILENAME} from Zenodo...")
        print(f"  URL: {ZENODO_URL}")
        print("  (This may take a minute, Zenodo can be slow)")

        resp = requests.get(ZENODO_URL, stream=True, timeout=120)
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
    csvs = list(extracted_dir.glob("**/*.csv")) if extracted_dir.exists() else []
    if not csvs:
        # Might have extracted to a different structure, search broadly
        csvs = list(out_dir.glob("**/*.csv"))

    print(f"  Extracted {len(csvs)} CSV files")
    for csv in csvs[:5]:
        print(f"    {csv.relative_to(out_dir)}")
    if len(csvs) > 5:
        print(f"    ... and {len(csvs) - 5} more")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Zenodo cleaned labels")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    download_labels(args.out_dir)
