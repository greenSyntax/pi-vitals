"""Rebuild frontend/icons/sprite.svg from a folder of Lucide SVG files.

Usage: python3 tools/build_sprite.py <folder-with-lucide-svgs>
Download icons from https://cdn.jsdelivr.net/npm/lucide-static@<version>/icons/<name>.svg
"""
import glob
import os
import re
import sys

src = sys.argv[1]
out = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">',
       '<!-- Lucide (ISC), see ../THIRD_PARTY.md. Regenerate with tools/build_sprite.py -->']
for path in sorted(glob.glob(os.path.join(src, "*.svg"))):
    name = os.path.basename(path)[:-4]
    inner = re.search(r"<svg[^>]*>(.*)</svg>", open(path).read(), re.S).group(1)
    inner = re.sub(r"\s*\n\s*", "", inner.strip())
    out.append(f'<symbol id="{name}" viewBox="0 0 24 24">{inner}</symbol>')
out.append("</svg>")
open(os.path.join(os.path.dirname(__file__), "..", "frontend", "icons", "sprite.svg"), "w").write("\n".join(out) + "\n")
