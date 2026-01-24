from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import requests


MBPP_URLS: List[str] = [
    # Primary (Google Research repo)
    "https://raw.githubusercontent.com/google-research/google-research/master/mbpp/mbpp.jsonl",
    # Mirror (sometimes packaged elsewhere)
    "https://raw.fastgit.org/google-research/google-research/master/mbpp/mbpp.jsonl",
]


def download_mbpp_jsonl(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for url in MBPP_URLS:
        try:
            with requests.get(url, timeout=60, stream=True) as r:
                r.raise_for_status()
                with output_path.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            print(f"Downloaded MBPP from {url} -> {output_path}")
            return
        except Exception as e:  # noqa: BLE001
            last_error = e
            print(f"Failed {url}: {e}")
    assert last_error is not None
    raise SystemExit(f"All MBPP sources failed. Last error: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download MBPP jsonl file")
    parser.add_argument("--out", type=Path, default=Path("data/mbpp.jsonl"))
    args = parser.parse_args()
    download_mbpp_jsonl(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


