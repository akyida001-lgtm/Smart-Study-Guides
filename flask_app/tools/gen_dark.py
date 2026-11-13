#!/usr/bin/env python3
"""Generate static/css/dark-extra.css.

The site's dark theme (html[data-theme="dark"]) was written by hand, one component at a time, so any
rule without a hand-written dark twin stayed light. This reads every stylesheet and every <style> block
and every inline style="..." in the templates, and writes a dark twin for each light surface, dark text
colour or light border that is not already covered.  Run:  python tools/gen_dark.py
"""
import colorsys, glob, os, re, sys
import tinycss2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DK = 'html[data-theme="dark"]'
SURFACE, SURFACE2, SURFACE3 = "#1e2a3a", "#253346", "#2a3d58"

def parse_color(v):
    v = v.strip().lower()
    if v == "white": return (255, 255, 255)
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v)
    if m:
        h = m.group(1); h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v)
    return tuple(int(x) for x in m.groups()) if m else None

def lum(c):
    f = lambda x: (x / 255 / 12.92) if x / 255 <= .03928 else (((x / 255) + .055) / 1.055) ** 2.4
    return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2])

def hls(c): return colorsys.rgb_to_hls(*(x / 255 for x in c))
def hexs(c): return "#%02x%02x%02x" % tuple(int(round(x * 255)) for x in c)

def dark_bg(c):
    """Light surface -> dark equivalent, or None to leave it."""
    L = lum(c)
    if L < 0.60: return None
    h, l, s = hls(c)
    if s < 0.28 or l > 0.97:                      # white / grey / very pale
        return SURFACE if L > 0.93 else SURFACE2 if L > 0.80 else SURFACE3
    r, g, b = colorsys.hls_to_rgb(h, 0.55, 0.65)   # pastel tint -> translucent version of its hue
    return f"rgba({int(r*255)},{int(g*255)},{int(b*255)},{0.20 if L < 0.85 else 0.14})"

def dark_text(c):
    """Dark text colour -> light equivalent, or None."""
    L = lum(c)
    if L > 0.32: return None
    h, l, s = hls(c)
    if s < 0.35:                                   # near-black / navy / slate text
        return "#dbe3ef" if L < 0.06 else "#c3cfe2" if L < 0.14 else "#93a5bf"
    r, g, b = colorsys.hls_to_rgb(h, 0.70, min(0.60, s))
    return hexs((r, g, b))

def dark_border(c):
    return SURFACE3 if lum(c) > 0.55 else None

EXCLUDE = re.compile(r"(gn-|tb-|theme-btn|nav-toggle|hamburger|topbar|snav|sidebar|dx-mast|dx-days|dx-bar|dx-pass|dx-tile\.lead|fd-reel|fd-lb|fd-toast|fd-mute|fd-cnt|fd-dots|fd-burst|fd-rail|fd-ract|app-topbar|nav-guest|\.nav\b|\.brand)")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,6}\b|\bwhite\b|rgb\([^)]*\)")

def transform(prop, value):
    """Return a replacement value for one declaration, or None."""
    v = value.strip()
    if prop.lower() == "color" and re.fullmatch(r"var\(--slate-(200|300)\)", v): return "#8c9eb9"
    if "gradient" in v or "url(" in v or "var(" in v: return None
    p = prop.lower()
    if p in ("background", "background-color"):
        c = parse_color(v.split("!")[0])
        if c is None: return None
        d = dark_bg(c); return d
    if p == "color":
        c = parse_color(v.split("!")[0].strip()); return dark_text(c) if c else None
    if p.startswith("border") and "radius" not in p and "collapse" not in p and "spacing" not in p:
        cols = COLOR_RE.findall(v)
        if not cols: return None
        out, changed = v, False
        for tok in cols:
            c = parse_color(tok)
            if c and dark_border(c): out = out.replace(tok, dark_border(c)); changed = True
        return out if changed else None
    if p in ("outline-color", "fill", "stroke"): return None
    return None

def selectors(prelude):
    sel = tinycss2.serialize(prelude).strip()
    out, depth, cur = [], 0, ""
    for ch in sel:
        if ch in "([": depth += 1
        elif ch in ")]": depth -= 1
        if ch == "," and depth == 0: out.append(cur.strip()); cur = ""
        else: cur += ch
    out.append(cur.strip()); return [s for s in out if s]

def walk(rules, emit):
    for r in rules:
        if r.type == "qualified-rule": emit(r)
        elif r.type == "at-rule" and r.lower_at_keyword in ("media", "supports") and r.content:
            walk(tinycss2.parse_rule_list(r.content, skip_comments=True, skip_whitespace=True), emit)

def sources():
    for f in ("static/css/styles.css", "static/css/human_writer.css", "static/css/feed.css"):
        yield f, open(os.path.join(ROOT, f), encoding="utf-8").read()
    for f in sorted(glob.glob(os.path.join(ROOT, "templates", "*.html"))):
        t = open(f, encoding="utf-8", errors="replace").read()
        for i, m in enumerate(re.finditer(r"<style[^>]*>(.*?)</style>", t, re.S)):
            css = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", m.group(1), flags=re.S)
            yield f"{os.path.basename(f)}#style{i}", css

def root_vars():
    css = open(os.path.join(ROOT, "static/css/styles.css"), encoding="utf-8").read()
    i = css.index(":root"); block = css[i:css.index("}", i)]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})", block)}

def contrast_white(c): return 1.05 / (lum(c) + .05)

def darken_for_white(c, target=4.6):
    """Lower the brightness (keep hue and saturation) until white text reaches the target contrast."""
    h, sat, v = colorsys.rgb_to_hsv(*(x / 255 for x in c))
    for _ in range(90):
        if contrast_white(tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h, sat, v))) >= target: break
        v -= 0.01
    return hexs(colorsys.hsv_to_rgb(h, sat, max(v, 0.05)))

def contrast_fix(parsed):
    """White text on a bright button/badge background: darken the background until the text is readable."""
    rv, out, seen = root_vars(), [], set()
    for name, rs in parsed:
        for r in rs:
            decls = {d.lower_name: tinycss2.serialize(d.value).strip() for d in tinycss2.parse_declaration_list(r.content, skip_comments=True, skip_whitespace=True) if d.type == "declaration"}
            bgv = decls.get("background-color") or decls.get("background")
            colv = (decls.get("color") or "").lower().replace("!important", "").strip()
            if not bgv or colv not in ("#fff", "#ffffff", "white"): continue
            bgv = bgv.replace("!important", "").strip()
            m = re.fullmatch(r"var\((--[\w-]+)\)", bgv)
            c = parse_color(rv.get(m.group(1), "")) if m else parse_color(bgv)
            if not c or contrast_white(c) >= 4.5 or lum(c) < 0.10: continue
            new = darken_for_white(c)
            for sel in selectors(r.prelude):
                if sel.startswith(DK) or re.match(r"^(html|body|:root)\b", sel) or EXCLUDE.search(sel): continue
                css = f"html {sel}{{background:{new}}}"
                if css not in seen: seen.add(css); out.append(css)
    return out

def main():
    covered, rules_out, seen = set(), [], set()
    parsed = []
    for name, css in sources():
        sheet = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
        collected = []
        walk(sheet, collected.append)
        parsed.append((name, collected))
    # 1) what the hand-written dark theme already covers
    for name, rs in parsed:
        for r in rs:
            for s in selectors(r.prelude):
                if s.startswith(DK):
                    base = re.sub(r"\s+", " ", s[len(DK):].strip())
                    for d in tinycss2.parse_declaration_list(r.content, skip_comments=True, skip_whitespace=True):
                        if d.type == "declaration":
                            covered.add((base, d.lower_name.split("-")[0] if d.lower_name.startswith("border") else ("background" if d.lower_name.startswith("background") else d.lower_name)))
    # 2) generate twins for everything else
    for name, rs in parsed:
        for r in rs:
            sels = [s for s in selectors(r.prelude) if not s.startswith(DK) and not s.startswith("@") and not re.match(r"^(html|body|:root)\b", s) and not EXCLUDE.search(s)]
            if not sels: continue
            decls = []
            for d in tinycss2.parse_declaration_list(r.content, skip_comments=True, skip_whitespace=True):
                if d.type != "declaration": continue
                val = tinycss2.serialize(d.value).strip()
                new = transform(d.lower_name, val)
                if new is None: continue
                kind = d.lower_name.split("-")[0] if d.lower_name.startswith("border") else ("background" if d.lower_name.startswith("background") else d.lower_name)
                decls.append((d.lower_name, new, kind))
            if not decls: continue
            keep = []
            for s in sels:
                base = re.sub(r"\s+", " ", s)
                want = [(p, v) for p, v, k in decls if (base, k) not in covered and not (k == "background" and re.search(r"::?(before|after)", s))]
                if want: keep.append((s, want))
            for s, want in keep:
                if "::" in s and not re.search(r"::(before|after|placeholder)", s): continue
                css = f"{DK} {s}{{" + ";".join(f"{p}:{v}" for p, v in want) + "}"
                if css not in seen: seen.add(css); rules_out.append(css)
    # 3) inline style="..." with light backgrounds / dark text
    inline = set()
    for f in sorted(glob.glob(os.path.join(ROOT, "templates", "*.html"))):
        t = open(f, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r'style="([^"]*)"', t):
            for prop, val in re.findall(r"(background(?:-color)?|color)\s*:\s*(#[0-9a-fA-F]{3,6}|white|var\(--slate-(?:200|300)\))(?![\w-])", m.group(1)):
                if prop.startswith("background") or True:
                    new = transform(prop, val)
                    if new and not re.search(r"[{}]", val):
                        for sp in (f"{prop}:{val}", f"{prop}: {val}"):
                            inline.add((f'[style*="{sp}"]', prop, new))
    for sel, prop, new in sorted(inline):
        rules_out.append(f"{DK} {sel}{{{prop}:{new} !important}}")
    fix = contrast_fix(parsed)
    open(os.path.join(ROOT, "static", "css", "contrast-fix.css"), "w", encoding="utf-8").write(
        "/* GENERATED by tools/gen_dark.py: darker backgrounds where white text was below 4.5:1. Do not edit by hand. */\n" + "\n".join(fix) + "\n")
    print(f"wrote contrast-fix.css: {len(fix)} rules")
    header = ("/* GENERATED by tools/gen_dark.py: dark twins for light surfaces, dark text and light borders.\n"
              "   Do not edit by hand; run `python tools/gen_dark.py` after adding styles. */\n")
    out = os.path.join(ROOT, "static", "css", "dark-extra.css")
    open(out, "w", encoding="utf-8").write(header + "\n".join(rules_out) + "\n")
    print(f"wrote {out}: {len(rules_out)} rules, {os.path.getsize(out)//1024} KB")

if __name__ == "__main__":
    main()
