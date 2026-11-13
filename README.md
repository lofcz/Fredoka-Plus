## Czech, Slovak and Polish

![Central European specimen](documentation/central-european.png)

Fredoka 2.001 lacks most Central European letters, so browsers fall back to another font in the middle of Czech, Slovak or Polish words. Version 2.002 of this fork adds them in all weights and widths:

| Language | Added letters |
| --- | --- |
| Czech | Č č Ď ď Ě ě Ň ň Ř ř Ť ť Ů ů |
| Slovak | Ľ ľ Ĺ ĺ Ŕ ŕ (with Ď ď Ť ť) |
| Polish | Ą ą Ć ć Ę ę Ń ń Ś ś Ź ź Ż ż |

### Building

```sh
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r scripts/requirements.txt
.venv/bin/python scripts/add_central_european.py   # adds the letters to sources/Fredoka.glyphs
.venv/bin/python scripts/build_release.py          # writes fonts/ and verifies the result
```

`build_release.py` adds the new glyphs to the mastered 2.001 binary (`sources/base/`) instead of recompiling every glyph. Current font tools build the 2.001 source with different kerning than the published font, so a full rebuild would change the spacing of text that already worked. The script checks that every existing glyph and every pair of existing characters shapes exactly as in 2.001, at nine weight and width combinations. It also checks that each new letter kerns like its base letter.

## License

This Font Software is licensed under the SIL Open Font License, Version 1.1 (see [OFL.txt](OFL.txt)).
