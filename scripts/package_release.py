"""Create release/PromptArchive-<version>.zip from dist/, host/, installer/, README and LICENSE.

Run `npm run build` first (or `npm run package`, which does both).
"""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

if not (DIST / "manifest.json").is_file():
    sys.exit("dist/manifest.json not found: run `npm run build` first")

version = json.loads((DIST / "manifest.json").read_text(encoding="utf-8"))["version"]
top = f"PromptArchive-{version}"
out = ROOT / "release" / f"{top}.zip"
out.parent.mkdir(exist_ok=True)

files = [(p, f"{top}/extension/{p.relative_to(DIST).as_posix()}") for p in sorted(DIST.rglob("*")) if p.is_file()]
files += [(ROOT / "host" / n, f"{top}/host/{n}") for n in ("export_prompt_history.py", "ai_chat_host.py")]
files += [(ROOT / "installer" / n, f"{top}/{n}") for n in ("install.cmd", "install.ps1", "uninstall.cmd", "uninstall.ps1")]
files += [(ROOT / "readme.md", f"{top}/README.md"), (ROOT / "LICENSE", f"{top}/LICENSE")]

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for src, name in files:
        if not src.is_file():
            sys.exit(f"missing {src}")
        z.write(src, name)

print(f"{out} ({out.stat().st_size // 1024} KB, {len(files)} files)")
