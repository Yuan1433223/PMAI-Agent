"""Download pinned Windows CPU runtime and weights into the ignored workspace data directory."""
import concurrent.futures
import argparse
import hashlib
import os
import shutil
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1] / "data/model"
CHUNK = 8 * 1024 * 1024
ASSETS = [
    ("llama-cpu.zip", 25096466, "0e2ff97a5ef40de3e4ca910231676c044e0813c54727b2012022a2d2401e1fa9",
     "https://github.com/ggml-org/llama.cpp/releases/download/b12649/llama-b12649-bin-win-cpu-x64.zip"),
    ("qwen-1.5b.gguf", 986048768, "1adf0b11065d8ad2e8123ea110d1ec956dab4ab038eab665614adba04b6c3370",
     "https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
     "9eadc66189c7641e1ddd226b8267a9119b2ce2d4/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"),
]


def download(asset):
    name, size, digest, url = asset
    target = ROOT / name
    if target.exists():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == digest:
                return
    parts = ROOT / (name + ".parts")
    parts.mkdir(exist_ok=True)

    def chunk(start):
        end = min(start + CHUNK, size) - 1
        path = parts / str(start)
        if path.exists() and path.stat().st_size == end - start + 1:
            return path
        for attempt in range(3):
            try:
                request = Request(url + f"?chunk={start}", headers={"Range": f"bytes={start}-{end}"})
                with urlopen(request, timeout=60) as reply:
                    if reply.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                        raise OSError("Unexpected byte range")
                    data = reply.read(end-start+2)
                if len(data) != end-start+1:
                    raise OSError("Incomplete chunk")
                path.write_bytes(data)
                return path
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(2 + attempt)

    partial = target.with_suffix(".partial")
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool, partial.open("wb") as output:
        for part in pool.map(chunk, range(0, size, CHUNK)):
            with part.open("rb") as stream:
                shutil.copyfileobj(stream, output)
    with partial.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError(f"{name}: checksum mismatch; remove {parts} before retrying")
    os.replace(partial, target)
    print(f"Verified {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights-only", action="store_true", help="Use an existing CPU runtime")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    for asset in ASSETS[1:] if args.weights_only else ASSETS:
        download(asset)
    if not args.weights_only:
        with zipfile.ZipFile(ROOT / ASSETS[0][0]) as archive:
            archive.extractall(ROOT / "llama-cpu")
