#!/usr/bin/env python3
"""Konvertuje Taxi.svg na Taxi.png pre pouzitie v emailoch."""

import sys
import os

SVG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Taxi.svg")
PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Taxi.png")

if not os.path.exists(SVG):
    print(f"❌ Súbor nenájdený: {SVG}")
    sys.exit(1)

# Pokus 1: cairosvg
try:
    import cairosvg
    cairosvg.svg2png(url=SVG, write_to=PNG, output_width=600)
    print(f"✅ Konvertované cez cairosvg → {PNG}")
    sys.exit(0)
except ImportError:
    pass
except Exception as e:
    print(f"cairosvg chyba: {e}")

# Pokus 2: svglib + reportlab
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    drawing = svg2rlg(SVG)
    renderPM.drawToFile(drawing, PNG, fmt="PNG")
    print(f"✅ Konvertované cez svglib → {PNG}")
    sys.exit(0)
except ImportError:
    pass
except Exception as e:
    print(f"svglib chyba: {e}")

# Pokus 3: Inkscape (ak je nainštalovaný)
import subprocess
for inkscape in [
    r"C:\Program Files\Inkscape\bin\inkscape.exe",
    r"C:\Program Files (x86)\Inkscape\inkscape.exe",
    "inkscape",
]:
    try:
        result = subprocess.run(
            [inkscape, SVG, f"--export-filename={PNG}", "--export-width=600"],
            capture_output=True, timeout=30
        )
        if result.returncode == 0 and os.path.exists(PNG):
            print(f"✅ Konvertované cez Inkscape → {PNG}")
            sys.exit(0)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        continue

print("❌ Žiadny konvertor nenájdený.")
print("   Nainštaluj jeden z:")
print("   pip install cairosvg")
print("   pip install svglib reportlab")
print("   alebo otvor Taxi.svg v prehliadači a ulož ako PNG")
