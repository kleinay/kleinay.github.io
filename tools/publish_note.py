#!/usr/bin/env python3
"""Turn a Google-Docs-flavoured markdown dump into a post for the notes site.

Usage:
    publish_note.py RAW.txt --doc-title "WeeklyAutoBlog 2026-08-23 - ..." \
                            [--doc-id <drive file id>] [--date YYYY-MM-DD]

Writes notes-<id>/posts/<slug>.json, refreshes posts.json, and creates the
per-post stub at notes-<id>/p/<slug>/index.html.

Google Docs escapes markdown punctuation on export (\\_, \\[, \\*, \\\\alpha)
and flattens fenced code into ordinary paragraphs, so both are undone here.
"""

import argparse
import datetime
import json
import pathlib
import re
import sys

SITE = pathlib.Path(__file__).resolve().parent.parent / "notes-24ddee3338"

ESCAPED = r"\\([\\`*_{}\[\]()#+\-.!<>|$~=&])"
CODE_START = re.compile(r"^(import |from \w[\w.]* import |def |class |@\w+$|\s{4}\S)")
HEADING = re.compile(r"^#{2,6}\s")
STATE_TRAILER = re.compile(r"^\s*-{2,}\s*WAB-STATE\s*-{2,}", re.M)


def unescape(text):
    """Drop the backslashes Google Docs adds in front of markdown punctuation.

    Also collapses LaTeX's doubled backslashes (\\\\alpha -> \\alpha), which is
    the same transformation applied to the `\\\\` case.
    """
    return re.sub(ESCAPED, r"\1", text)


def strip_state_trailer(text):
    """Remove the WAB-STATE bookkeeping block the generator appends."""
    m = STATE_TRAILER.search(text)
    return text[: m.start()] if m else text


def is_prose(line):
    """A sentence-looking line, used to detect where a flattened code block ends."""
    if not line or not line[0].isupper():
        return False
    if any(c in line for c in "=([_"):
        return False
    return line.rstrip().endswith((".", ":", "?")) and len(line.split()) > 6


def refence_code(text):
    """Re-fence code that Docs flattened into blank-line-separated paragraphs."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not CODE_START.match(line):
            out.append(line)
            i += 1
            continue
        block, j = [], i
        while j < len(lines):
            cur = lines[j]
            if not cur.strip():
                j += 1
                continue
            if HEADING.match(cur) or is_prose(cur):
                break
            block.append(cur)
            j += 1
        # A single line matching CODE_START is more likely prose than a program.
        if len(block) < 2:
            out.append(line)
            i += 1
            continue
        out.extend(["", "```python", *block, "```", ""])
        i = j
    return "\n".join(out)


def fix_blank_header_tables(text):
    """Promote the first body row of tables whose header row is empty."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        header, sep = lines[i], lines[i + 1] if i + 1 < len(lines) else ""
        blank_header = (
            header.startswith("|")
            and re.fullmatch(r"\|(\s*\|)+", header.strip())
            and re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", sep.strip() or "x")
        )
        if blank_header and i + 2 < len(lines) and lines[i + 2].startswith("|"):
            out.extend([lines[i + 2], sep])
            i += 3
            continue
        out.append(header)
        i += 1
    return "\n".join(out)


def tidy(text):
    text = "\n".join(l.rstrip() for l in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


STOPWORDS = {
    "a", "an", "the", "of", "on", "in", "is", "it", "that", "this", "and", "or",
    "for", "to", "at", "as", "was", "were", "you", "your", "what", "not", "but",
}


def slugify(title):
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", title.lower()).split() if w]
    kept = words[:7]
    while kept and kept[-1] in STOPWORDS:  # don't end a slug on a dangling "that"
        kept.pop()
    return "-".join(kept) or "note"


def split_front(body):
    """Pull the H1 title, the `10 min read` byline, and a summary out of the body."""
    lines = body.split("\n")
    title, byline, start = None, None, 0
    for idx, line in enumerate(lines):
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            start = idx + 1
            continue
        if title is not None:
            if not line.strip():
                start = idx + 1
                continue
            m = re.fullmatch(r"\*(.+?)\*", line.strip())
            if m and byline is None:
                byline, start = m.group(1).strip(), idx + 1
            break
    rest = "\n".join(lines[start:]).strip()
    first = next((p for p in rest.split("\n\n") if p.strip()), "")
    summary = re.sub(r"\s+", " ", re.sub(r"[*_`$\\]", "", first)).strip()
    if len(summary) > 240:
        summary = summary[:237].rsplit(" ", 1)[0] + "..."
    return title, byline, rest, summary


def convert(raw, doc_title):
    # Unescape first: the trailer is written "\--- WAB-STATE \---" in the export,
    # so it only matches once the backslashes are gone.
    body = tidy(fix_blank_header_tables(refence_code(strip_state_trailer(unescape(raw)))))
    title, byline, rest, summary = split_front(body)
    if title is None:  # fall back to the Drive filename after the date prefix
        title = re.sub(r"^WeeklyAutoBlog\s+\d{4}-\d{2}-\d{2}\s*-\s*", "", doc_title).strip()
        rest = body
    return title, byline, rest, summary


def write_post(post):
    slug = post["slug"]
    (SITE / "posts" / f"{slug}.json").write_text(
        json.dumps(post, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    stub_dir = SITE / "p" / slug
    stub_dir.mkdir(parents=True, exist_ok=True)
    tpl = pathlib.Path(__file__).resolve().parent / "templates" / "post.html"
    stub = tpl.read_text(encoding="utf-8")
    (stub_dir / "index.html").write_text(
        stub.replace("__SLUG__", slug).replace("__TITLE__", post["title"]),
        encoding="utf-8",
    )


def rebuild_index():
    posts = []
    for f in sorted((SITE / "posts").glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        posts.append({k: p[k] for k in ("slug", "title", "byline", "summary", "date")})
    posts.sort(key=lambda p: p["date"], reverse=True)
    (SITE / "posts.json").write_text(
        json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=pathlib.Path)
    ap.add_argument("--doc-title", default="")
    ap.add_argument("--doc-id", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--slug", default="")
    args = ap.parse_args()

    date = args.date
    if not date:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", args.doc_title)
        date = m.group(1) if m else datetime.date.today().isoformat()

    raw = args.raw.read_text(encoding="utf-8")
    title, byline, body, summary = convert(raw, args.doc_title)
    slug = args.slug or slugify(title)

    post = {
        "slug": slug,
        "title": title,
        "byline": byline or "",
        "summary": summary,
        "date": date,
        "docId": args.doc_id,
        "body": body,
    }
    write_post(post)
    rebuild_index()
    print(f"{slug}\t{title}")
    print(f"/notes-24ddee3338/p/{slug}/")


if __name__ == "__main__":
    sys.exit(main())
