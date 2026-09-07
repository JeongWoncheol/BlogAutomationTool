# -*- coding: utf-8 -*-
from pathlib import Path
import os, shutil, json

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "chrome_extension"

def stable_extension_dir():
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "NaverBlogAutomationStudio" / "chrome_extension"
    return ROOT / "_stable_chrome_extension"

def sync_extension():
    dst = stable_extension_dir()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        # Preserve no user data inside extension folder; source of truth is program.
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst)
    return dst

if __name__ == "__main__":
    p = sync_extension()
    print(p)
