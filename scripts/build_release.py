"""Build the Central European release: the mastered 2.001 font plus the new letters.

Rebuilding the whole font from sources/Fredoka.glyphs with current tools
changes the spacing of text that already worked: the 2.001 binary (the one
Google Fonts serves) applies two stacked kern lookups, so pairs such as Ka,
GV or .V get glyph and class kerning added together, and its Light masters
kern differently from Bold. The source alone does not reproduce that.

So the release keeps every byte of the 2.001 font that existing text uses and
adds only the new glyphs:

1. Build the edited source with fontmake (the donor) for the new glyphs'
   outlines, advances and variations.
2. Copy those glyphs into sources/base/Fredoka-2.001[wdth,wght].ttf, encode
   them, classify them in GDEF and rebuild HVAR from the variations.
3. Kerning: each new letter kerns the way the font already kerns its
   accented letters. It joins every kern class of its base letter (č kerns
   like c), and the glyph pairs of every subtable where é á š Á already
   follow their bases. The second kern lookup holds the large exceptions
   (T→e -120, V→A) for plain letters only, so accents never run into a
   crossbar; new letters stay out of those too. Letters with the vertical
   caron (ď ť ľ Ľ) keep only their left side.
4. Check that every existing glyph, advance and kern pair is unchanged.
5. Write the variable font, the static TTFs and OTFs (overlaps removed) and
   the WOFF2 web fonts.

    .venv/bin/python scripts/build_release.py
"""

from __future__ import annotations

import copy
import itertools
import subprocess
import sys
import tempfile
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTFont
from fontTools.varLib.hvar import add_HVAR
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.varLib.instancer import OverlapMode, instantiateVariableFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_central_european import ALT_GLYPHS, COMPOSITES, SPECIAL  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "sources" / "base" / "Fredoka-2.001[wdth,wght].ttf"
SOURCE = ROOT / "sources" / "Fredoka.glyphs"
FONTS = ROOT / "fonts"
VERSION = "2.002"
STATICS = {"Light": 300, "Regular": 400, "Medium": 500, "SemiBold": 600, "Bold": 700}

# Base letter of every new glyph (production names, as in the compiled font).
BASE_OF = {name: base for name, (_, base, *_rest) in COMPOSITES.items()}
BASE_OF.update({name: base for name, (_, base) in SPECIAL.items()})
NO_RIGHT_KERNING = set(ALT_GLYPHS)


def build_donor(directory: Path) -> TTFont:
    out = directory / "donor.ttf"
    subprocess.run(
        [sys.executable, "-m", "fontmake", "-g", str(SOURCE), "-o", "variable", "--output-path", str(out)],
        check=True,
        capture_output=True,
    )
    return TTFont(out)


def add_glyphs(font: TTFont, donor: TTFont) -> list[str]:
    known = set(font.getGlyphOrder())
    # newsheqel is uni20AA in newer builds; it is not new.
    new = [g for g in donor.getGlyphOrder() if g not in known and g != "uni20AA"]
    marks = {g for g in new if g not in BASE_OF}
    assert set(BASE_OF) <= set(new), sorted(set(BASE_OF) - set(new))
    assert marks == {"uni030C.alt", "uni030A.uring", "uni030A.uring.case"}, sorted(marks)
    font.setGlyphOrder(font.getGlyphOrder() + new)
    glyf, hmtx, gvar = font["glyf"], font["hmtx"], font["gvar"]
    for name in new:
        glyph = copy.deepcopy(donor["glyf"][name])
        if glyph.isComposite():
            for component in glyph.components:
                assert component.glyphName in known or component.glyphName in new, component.glyphName
        glyf[name] = glyph
        hmtx[name] = donor["hmtx"][name]
        gvar.variations[name] = copy.deepcopy(donor["gvar"].variations.get(name, []))
    for name in new:
        glyf[name].recalcBounds(glyf)
        hmtx[name] = (hmtx[name][0], getattr(glyf[name], "xMin", 0))
    # Encode, classify and refresh the advance variations.
    donor_cmap = donor.getBestCmap()
    for table in font["cmap"].tables:
        if table.isUnicode():
            for code, name in donor_cmap.items():
                if name in new:
                    table.cmap[code] = name
    classes = font["GDEF"].table.GlyphClassDef.classDefs
    for name in new:
        classes[name] = 1 if name in BASE_OF else 3
    add_HVAR(font)
    font["maxp"].numGlyphs = len(font.getGlyphOrder())
    return new


def pair_lookups(font: TTFont):
    for lookup in font["GPOS"].table.LookupList.Lookup:
        for sub in lookup.SubTable:
            sub = sub.ExtSubTable if lookup.LookupType == 9 else sub
            if type(sub).__name__ == "PairPos":
                yield sub


# Existing accented letters and their bases, to learn where accents follow bases.
SIBLINGS = [("eacute", "e"), ("aacute", "a"), ("scaron", "s"), ("uacute", "u"), ("ntilde", "n"),
            ("ccedilla", "c"), ("Aacute", "A"), ("Scaron", "S"), ("Uacute", "U"), ("Eacute", "E")]


def accents_follow_bases(sub) -> bool:
    """Whether existing accented letters share their base's glyph pairs here."""
    seconds: dict[str, int] = {}
    for pair_set in sub.PairSet:
        for record in pair_set.PairValueRecord:
            seconds[record.SecondGlyph] = seconds.get(record.SecondGlyph, 0) + 1
    firsts = set(sub.Coverage.glyphs)
    votes = [
        (accented in firsts) == (base in firsts) and seconds.get(accented, 0) == seconds.get(base, 0)
        for accented, base in SIBLINGS
        if base in firsts or base in seconds
    ]
    return sum(votes) * 2 > len(votes)


def add_kerning(font: TTFont, new: list[str]) -> list[int]:
    """Returns the ids of glyph-pair subtables that stay plain-letter only."""
    gid = font.getGlyphID
    letters = [n for n in new if n in BASE_OF]
    plain_only = []
    for sub in pair_lookups(font):
        coverage = sub.Coverage.glyphs
        if sub.Format == 1 and not accents_follow_bases(sub):
            plain_only.append(id(sub))
            continue
        if sub.Format == 1:
            pairs = dict(zip(coverage, sub.PairSet))
            for name in letters:
                base = BASE_OF[name]
                if base in pairs and name not in NO_RIGHT_KERNING:
                    pairs[name] = copy.deepcopy(pairs[base])
            for pair_set in pairs.values():
                records = pair_set.PairValueRecord
                by_second = {r.SecondGlyph: r for r in records}
                for name in letters:
                    if BASE_OF[name] in by_second and name not in by_second:
                        record = copy.deepcopy(by_second[BASE_OF[name]])
                        record.SecondGlyph = name
                        records.append(record)
                records.sort(key=lambda r: gid(r.SecondGlyph))
                pair_set.PairValueCount = len(records)
            ordered = sorted(pairs, key=gid)
            sub.Coverage.glyphs = ordered
            sub.PairSet = [pairs[g] for g in ordered]
            sub.PairSetCount = len(ordered)
        else:
            first, second = sub.ClassDef1.classDefs, sub.ClassDef2.classDefs
            covered = set(coverage)
            for name in letters:
                base = BASE_OF[name]
                if base in covered and name not in NO_RIGHT_KERNING:
                    covered.add(name)
                    if base in first:
                        first[name] = first[base]
                if base in second:
                    second[name] = second[base]
            sub.Coverage.glyphs = sorted(covered, key=gid)
    return plain_only


def set_version(font: TTFont) -> None:
    font["head"].fontRevision = float(VERSION)
    for record in font["name"].names:
        text = record.toUnicode()
        if "2.001" in text:
            record.string = text.replace("2.001", VERSION)


def shape(data: bytes, text: str, location: dict):
    font = hb.Font(hb.Face(data))
    font.set_variations(location)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    return [(i.codepoint, p.x_advance, p.x_offset, p.y_offset) for i, p in zip(buf.glyph_infos, buf.glyph_positions)]


def without_plain_only(font_path: Path) -> bytes:
    """The font without the plain-letter exceptions: what new letters should match."""
    font = TTFont(font_path)
    for lookup in font["GPOS"].table.LookupList.Lookup:
        if lookup.LookupType == 2:
            lookup.SubTable = [s for s in lookup.SubTable if s.Format == 2 or accents_follow_bases(s)]
            lookup.SubTableCount = len(lookup.SubTable)
    out = tempfile.NamedTemporaryFile(suffix=".ttf", delete=False).name
    font.save(out)
    return Path(out).read_bytes()


def verify(base_path: Path, font_path: Path, new: list[str]) -> None:
    base, font = TTFont(base_path), TTFont(font_path)
    old_data, new_data = base_path.read_bytes(), font_path.read_bytes()
    shared = base.getGlyphOrder()
    assert font.getGlyphOrder()[: len(shared)] == shared
    for name in shared:
        assert base["glyf"][name].getCoordinates(base["glyf"])[0] == font["glyf"][name].getCoordinates(font["glyf"])[0], name
    chars = [chr(c) for c in base.getBestCmap() if 0x20 < c < 0x250]
    locations = [{"wght": w, "wdth": s} for w in (300, 500, 700) for s in (75, 100, 125)]
    for location in locations:
        for a, b in itertools.product(chars, repeat=2):
            assert shape(old_data, a + b, location) == shape(new_data, a + b, location), (location, a + b)
    print(f"verified: {len(shared)} existing glyphs and {len(chars) ** 2} pairs unchanged at {len(locations)} locations")
    # New letters kern like their bases do outside the plain-letter exceptions
    # (left side always, right side unless vertical caron).
    reference = without_plain_only(font_path)
    cmap = {v: chr(k) for k, v in font.getBestCmap().items()}
    checked = 0
    for name in new:
        if name not in BASE_OF:
            continue
        letter, base_letter = cmap[name], cmap[BASE_OF[name]]
        for other in "TVWYAPLFKoaev":
            for location in ({"wght": 300, "wdth": 100}, {"wght": 700, "wdth": 100}):
                left = shape(new_data, other + letter, location)[0][1:]
                assert left == shape(reference, other + base_letter, location)[0][1:], (other + letter, location)
                if name not in NO_RIGHT_KERNING:
                    width_new = shape(new_data, letter + other, location)[0][1] - font["hmtx"][name][0]
                    width_base = shape(reference, base_letter + other, location)[0][1] - font["hmtx"][BASE_OF[name]][0]
                    assert width_new == width_base, (letter + other, location)
                checked += 1
    print(f"verified: {checked} kerning contexts of the new letters match their base letters")


def to_otf(ttf_path: Path, otf_path: Path) -> None:
    """Static TTF to CFF-flavoured OTF with the same tables and kerning."""
    font = TTFont(ttf_path)
    glyphs = font.getGlyphSet()
    charstrings = {}
    for name in font.getGlyphOrder():
        pen = T2CharStringPen(font["hmtx"][name][0], glyphs)
        glyphs[name].draw(pen)
        charstrings[name] = pen.getCharString()
    for tag in ("glyf", "loca", "fpgm", "cvt ", "prep"):
        if tag in font:
            del font[tag]
    name = font["name"]
    builder = FontBuilder(font=font, isTTF=False)
    builder.setupCFF(
        name.getDebugName(6),
        {
            "FullName": name.getDebugName(4),
            "FamilyName": name.getDebugName(1),
            "Weight": name.getDebugName(2),
            "version": VERSION,
            "Notice": name.getDebugName(0) or "",
        },
        charstrings,
        {},
    )
    builder.setupMaxp()
    font["post"].formatType = 3.0
    font["post"].extraNames, font["post"].mapping = [], {}
    font.sfntVersion = "OTTO"
    font.save(otf_path)


def write_outputs(font_path: Path) -> None:
    variable = TTFont(font_path)
    variable.flavor = "woff2"
    variable.save(FONTS / "webfonts" / "Fredoka[wdth,wght].woff2")
    for style, weight in STATICS.items():
        static = instantiateVariableFont(
            TTFont(font_path), {"wght": weight, "wdth": 100}, updateFontNames=True, overlap=OverlapMode.REMOVE
        )
        ttf = FONTS / "ttf" / f"Fredoka-{style}.ttf"
        static.save(ttf)
        to_otf(ttf, FONTS / "otf" / f"Fredoka-{style}.otf")
        static.flavor = "woff2"
        static.save(FONTS / "webfonts" / f"Fredoka-{style}.woff2")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        donor = build_donor(Path(tmp))
        font = TTFont(BASE)
        font.ensureDecompiled()  # tables decompile lazily; the glyph order is about to grow
        new = add_glyphs(font, donor)
        plain_only = add_kerning(font, new)
        print(f"kerning: {len(plain_only)} glyph-pair subtable(s) kept for plain letters only")
        set_version(font)
        out = FONTS / "variable" / "Fredoka[wdth,wght].ttf"
        font.save(out)
    print(f"{out.relative_to(ROOT)}: {len(new)} glyphs added, version {VERSION}")
    verify(BASE, out, new)
    write_outputs(out)
    print("static TTFs, OTFs and WOFF2 web fonts written")


if __name__ == "__main__":
    main()
