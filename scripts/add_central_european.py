"""Add the Czech, Slovak and Polish letters Fredoka lacks to sources/Fredoka.glyphs.

German is already covered (ä ö ü ß Ä Ö Ü „ “ ‚ ‘). The script composes the
missing letters from the font's own bases and marks, in every master:

- Mark placement follows the source's anchors, exactly as the existing
  composites do (offset = base anchor - mark anchor). The script verifies that
  rule against the composites already in the font before it adds anything.
- Slovak/Czech ď ť ľ Ľ take the vertical caron: a new caroncomb.alt glyph
  drawn from the font's own comma (the shape of ’), set beside the stem.
- ĺ places the cap acute above the ascender.

Run it again at any time: it replaces the glyphs it added before.

    .venv/bin/python scripts/add_central_european.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from glyphsLib.classes import GSComponent, GSFont, GSGlyph, GSLayer

SOURCE = Path(__file__).resolve().parent.parent / "sources" / "Fredoka.glyphs"

# Vertical caron: scale of the comma (’), gap to the stem.
ALT_SCALE = 0.8
ALT_GAP = 32
ALT_MIN_RSB = 18
ALT_GLYPHS = {"dcaron", "tcaron", "lcaron", "Lcaron"}

# name: (unicode, base, mark, base anchor, kerning-group source)
COMPOSITES: dict[str, tuple[str, str, str, str]] = {
    # Czech
    "Ccaron": ("010C", "C", "caroncomb.case", "top"),
    "ccaron": ("010D", "c", "caroncomb", "top"),
    "Dcaron": ("010E", "D", "caroncomb.case", "top"),
    "Ecaron": ("011A", "E", "caroncomb.case", "top"),
    "ecaron": ("011B", "e", "caroncomb", "top"),
    "Ncaron": ("0147", "N", "caroncomb.case", "top"),
    "ncaron": ("0148", "n", "caroncomb", "top"),
    "Rcaron": ("0158", "R", "caroncomb.case", "top"),
    "rcaron": ("0159", "r", "caroncomb", "top"),
    "Tcaron": ("0164", "T", "caroncomb.case", "top"),
    "Uring": ("016E", "U", "ringcomb.case", "top"),
    "uring": ("016F", "u", "ringcomb", "top"),
    # Slovak
    "Lacute": ("0139", "L", "acutecomb.case", "top"),
    "Racute": ("0154", "R", "acutecomb.case", "top"),
    "racute": ("0155", "r", "acutecomb", "top"),
    # Polish
    "Aogonek": ("0104", "A", "ogonekcomb", "ogonek"),
    "aogonek": ("0105", "a", "ogonekcomb", "ogonek"),
    "Cacute": ("0106", "C", "acutecomb.case", "top"),
    "cacute": ("0107", "c", "acutecomb", "top"),
    "Eogonek": ("0118", "E", "ogonekcomb", "ogonek"),
    "eogonek": ("0119", "e", "ogonekcomb", "ogonek"),
    "Nacute": ("0143", "N", "acutecomb.case", "top"),
    "nacute": ("0144", "n", "acutecomb", "top"),
    "Sacute": ("015A", "S", "acutecomb.case", "top"),
    "sacute": ("015B", "s", "acutecomb", "top"),
    "Zacute": ("0179", "Z", "acutecomb.case", "top"),
    "zacute": ("017A", "z", "acutecomb", "top"),
    "Zdotaccent": ("017B", "Z", "dotaccentcomb.case", "top"),
    "zdotaccent": ("017C", "z", "dotaccentcomb", "top"),
}
# Vertical-caron letters and ĺ are placed by outline, not by anchor.
SPECIAL = {
    "dcaron": ("010F", "d"),
    "tcaron": ("0165", "t"),
    "lcaron": ("013E", "l"),
    "Lcaron": ("013D", "L"),
    "lacute": ("013A", "l"),
}
ALT_MARK = "caroncomb.alt"
ADDED = set(COMPOSITES) | set(SPECIAL) | {ALT_MARK}


def anchor(layer: GSLayer, name: str) -> tuple[float, float]:
    for a in layer.anchors:
        if a.name == name:
            return (a.position.x, a.position.y)
    raise KeyError(f"{layer.parent.name} / {layer.name}: no anchor {name}")


def points(layer: GSLayer):
    for path in layer.paths:
        for node in path.nodes:
            yield node.position.x, node.position.y


def box(layer: GSLayer) -> tuple[float, float, float, float]:
    xs, ys = zip(*points(layer))
    return min(xs), min(ys), max(xs), max(ys)


def stem_right(layer: GSLayer, top: float, band: float) -> float:
    """Right edge of the outline in the topmost band (the stem's top)."""
    return max(x for x, y in points(layer) if y >= top - band)


def check_rule(font: GSFont) -> None:
    """The existing composites must sit at base anchor - mark anchor."""
    checked = worst = 0
    for name in ("scaron", "zcaron", "Scaron", "Zcaron", "aring", "Aring", "eacute", "aacute", "uacute", "yacute"):
        glyph = font.glyphs[name]
        for master in font.masters:
            layer = glyph.layers[master.id]
            base, mark = layer.components
            want = tuple(
                b - m
                for b, m in zip(
                    anchor(font.glyphs[base.name].layers[master.id], "top"),
                    anchor(font.glyphs[mark.name].layers[master.id], "_top"),
                )
            )
            got = tuple(mark.position)
            worst = max(worst, abs(want[0] - got[0]), abs(want[1] - got[1]))
            checked += 1
    print(f"anchor rule: {checked} existing placements, largest deviation {worst:g} units")
    if worst > 1:
        sys.exit("existing composites do not follow the anchor rule; placement would differ")


def new_glyph(font: GSFont, name: str, unicode: str | None, groups_from: str | None) -> GSGlyph:
    glyph = GSGlyph(name)
    if unicode:
        glyph.unicode = unicode
    if groups_from:
        source = font.glyphs[groups_from]
        glyph.leftKerningGroup = source.leftKerningGroup
        glyph.rightKerningGroup = source.rightKerningGroup
    font.glyphs.append(glyph)
    return glyph


def add_layer(glyph: GSGlyph, master_id: str, width: float, components) -> GSLayer:
    layer = GSLayer()
    layer.layerId = master_id
    layer.associatedMasterId = master_id
    layer.width = round(width)
    glyph.layers.append(layer)
    for name, (x, y) in components:
        layer.components.append(GSComponent(name, offset=(round(x), round(y))))
    return layer


def add_alt_mark(font: GSFont) -> None:
    glyph = new_glyph(font, ALT_MARK, None, None)
    glyph.category, glyph.subCategory = "Mark", "Nonspacing"
    for master in font.masters:
        # quoteright is a shifted comma component; scale the comma outline.
        quote = font.glyphs["comma"].layers[master.id]
        layer = add_layer(glyph, master.id, 0, [])
        for path in quote.paths:
            path = copy.deepcopy(path)
            for node in path.nodes:
                node.position = (round(node.position.x * ALT_SCALE), round(node.position.y * ALT_SCALE))
            layer.paths.append(path)


def add_composites(font: GSFont) -> None:
    for name, (unicode, base, mark, base_anchor) in COMPOSITES.items():
        glyph = new_glyph(font, name, unicode, base)
        for master in font.masters:
            base_layer = font.glyphs[base].layers[master.id]
            bx, by = anchor(base_layer, base_anchor)
            mx, my = anchor(font.glyphs[mark].layers[master.id], f"_{base_anchor}")
            add_layer(glyph, master.id, base_layer.width, [(base, (0, 0)), (mark, (bx - mx, by - my))])


def add_special(font: GSFont) -> None:
    for name, (unicode, base) in SPECIAL.items():
        # The vertical caron sticks out on the right: keep the left kerning only.
        glyph = new_glyph(font, name, unicode, base)
        if name in ALT_GLYPHS:
            glyph.rightKerningGroup = None
        for master in font.masters:
            base_layer = font.glyphs[base].layers[master.id]
            x0, _, x1, top = box(base_layer)
            if name == "lacute":
                # Cap acute over the ascender, as high above it as Á sits above A.
                cap_top = box(font.glyphs["L"].layers[master.id])[3]
                mark = font.glyphs["acutecomb.case"].layers[master.id]
                bx, _ = anchor(base_layer, "top")
                mx, my = anchor(mark, "_top")
                dy = top + (master.capHeight - cap_top) - my
                add_layer(glyph, master.id, base_layer.width, [(base, (0, 0)), ("acutecomb.case", (bx - mx, dy))])
                continue
            alt = font.glyphs[ALT_MARK].layers[master.id]
            ax0, _, ax1, ay1 = box(alt)
            band = 90 if base == "t" else 140
            dx = stem_right(base_layer, top, band) + ALT_GAP - ax0
            # Align the caron's top with the stem; t is short, so lift it to the ascender.
            align = box(font.glyphs["l"].layers[master.id])[3] if base == "t" else top
            dy = align - ay1
            rsb = max(ALT_MIN_RSB, base_layer.width - x1)
            width = max(base_layer.width, dx + ax1 + rsb)
            add_layer(glyph, master.id, width, [(base, (0, 0)), (ALT_MARK, (dx, dy))])


def main() -> None:
    font = GSFont(str(SOURCE))
    for name in ADDED:
        if font.glyphs[name] is not None:
            del font.glyphs[name]
    existing = [n for n in ("ccaron", "rcaron", "aogonek") if font.glyphs[n] is not None]
    assert not existing, existing
    check_rule(font)
    add_alt_mark(font)
    add_composites(font)
    add_special(font)
    # Upstream is 2.001; the Central European release is 2.002.
    font.versionMinor = max(font.versionMinor, 2)
    font.save(str(SOURCE))
    print(f"added {len(ADDED)} glyphs to {SOURCE.name}; version {font.versionMajor}.{font.versionMinor:03d}")


if __name__ == "__main__":
    main()
