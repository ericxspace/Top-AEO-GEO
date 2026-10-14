"""Shared helpers for the retro-radius-geo-audit scripts.

Stdlib only (no bs4/requests/playwright) so the scripts run in any routine
session with plain Python 3.10+. Read-only: every function here GETs public
storefront URLs and never writes anywhere except stdout / an --out file.
"""
import gzip
import json
import re
import time
import urllib.error
import urllib.request
import zlib
from html.parser import HTMLParser

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# ---------------------------------------------------------------- fetching


def fetch(url, ua=BROWSER_UA, accept=None, timeout=30, retries=3):
    """GET with backoff on 429/503. Shopify throttles one IP that fires hundreds of requests
    (2026-10-14: two parallel scans drew 429s on 55 bot x URL pairs). A 429 that survives the
    retries is OUR scan rate, not evidence that the real crawler is blocked. The result carries
    'retries_used' so callers can tell."""
    r = _fetch_once(url, ua, accept, timeout)
    used = 0
    while r["status"] in (429, 503) and used < retries:
        try:
            wait = float(r["headers"].get("retry-after", "") or 0)
        except ValueError:
            wait = 0
        time.sleep(min(max(wait, 2 * 2 ** used), 30))
        used += 1
        r = _fetch_once(url, ua, accept, timeout)
    r["retries_used"] = used
    return r


def _fetch_once(url, ua, accept, timeout):
    headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    status, hdrs, raw, final, err = 0, None, b"", url, None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, hdrs, raw, final = r.status, r.headers, r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        status, hdrs = e.code, e.headers
        try:
            raw = e.read()
        except Exception:
            raw = b""
    except Exception as e:  # DNS, TLS, timeout
        err = f"{type(e).__name__}: {e}"
    out_headers = {}
    if hdrs is not None:
        for k in set(k.lower() for k in hdrs.keys()):
            out_headers[k] = ", ".join(hdrs.get_all(k) or [])
    enc = out_headers.get("content-encoding", "").lower()
    try:
        if "gzip" in enc:
            raw = gzip.decompress(raw)
        elif "deflate" in enc:
            raw = zlib.decompress(raw)
    except Exception:
        pass
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", out_headers.get("content-type", ""), re.I)
    if m:
        charset = m.group(1)
    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    return {"url": url, "final_url": final, "status": status, "headers": out_headers,
            "body": body, "bytes": len(raw), "error": err}


def served_theme_id(headers):
    """Shopify server-timing carries theme;desc="<id>" — the theme that actually served the page."""
    m = re.search(r'theme;desc="?(\d+)', headers.get("server-timing", ""))
    return m.group(1) if m else None


# ---------------------------------------------------------------- tiny DOM

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
BLOCK = {"p", "div", "ul", "ol", "table", "section", "article", "h1", "h2", "h3", "h4",
         "h5", "h6", "blockquote", "figure", "details", "form"}
SKIP_TEXT = {"script", "style", "noscript", "svg", "template", "iframe"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, attrs or {}, [], parent

    def get(self, key, default=""):
        return self.attrs.get(key) or default


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK and self.cur.tag == "p":       # implicit </p>
            self.cur = self.cur.parent
        if tag == "li" and self.cur.tag == "li":        # implicit </li>
            self.cur = self.cur.parent
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if data:
            self.cur.children.append(data)


def parse_html(html):
    b = _Builder()
    try:
        b.feed(html)
        b.close()
    except Exception:
        pass
    return b.root


def iter_nodes(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, Node):
            yield n
            stack.extend(reversed([c for c in n.children if isinstance(c, Node)]))


def find_all(node, tags):
    tags = {tags} if isinstance(tags, str) else set(tags)
    return [n for n in iter_nodes(node) if n.tag in tags]


def first(node, tags):
    hits = find_all(node, tags)
    return hits[0] if hits else None


def text_of(node, skip=SKIP_TEXT):
    parts = []

    def walk(n):
        for c in n.children:
            if isinstance(c, str):
                parts.append(c)
            elif c.tag not in skip:
                if c.tag in BLOCK or c.tag in ("br", "li", "tr", "td", "th"):
                    parts.append(" ")
                walk(c)
                if c.tag in BLOCK or c.tag in ("li", "tr"):
                    parts.append(" ")
    if isinstance(node, Node):
        walk(node)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def meta_content(root, name=None, prop=None):
    for m in find_all(root, "meta"):
        if name and m.get("name").lower() == name:
            return m.get("content")
        if prop and m.get("property").lower() == prop:
            return m.get("content")
    return ""


def canonical(root):
    for l in find_all(root, "link"):
        if "canonical" in l.get("rel").lower().split():
            return l.get("href")
    return ""


# ---------------------------------------------------------------- JSON-LD

def jsonld_blocks(root):
    """Return (parsed_objects, errors) for every <script type=application/ld+json>."""
    objs, errs = [], []
    for s in find_all(root, "script"):
        if "ld+json" not in s.get("type").lower():
            continue
        raw = "".join(c for c in s.children if isinstance(c, str)).strip()
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw)
        try:
            objs.append(json.loads(raw))
        except Exception as e:
            try:  # tolerate trailing commas
                objs.append(json.loads(re.sub(r",\s*([}\]])", r"\1", raw)))
            except Exception:
                errs.append(f"{type(e).__name__}: {str(e)[:80]}")
    return objs, errs


def iter_typed(obj):
    """Yield every dict that carries an @type, recursively (handles @graph and nesting)."""
    if isinstance(obj, dict):
        if "@type" in obj:
            yield obj
        for v in obj.values():
            yield from iter_typed(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_typed(v)


def types_of(d):
    t = d.get("@type")
    return [t] if isinstance(t, str) else [x for x in (t or []) if isinstance(x, str)]


# ---------------------------------------------------------------- text utils

WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")


def words(text):
    return WORD_RE.findall(text or "")


def sentences(text):
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", text)
    return [p.strip() for p in parts if p.strip()]


def norm_phrase(s):
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split()


def contains_phrase(text, phrase):
    """Word-boundary, punctuation-insensitive containment."""
    t, p = " ".join(norm_phrase(text)), " ".join(norm_phrase(phrase))
    return bool(p) and f" {p} " in f" {t} "


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(obj, out_path=None):
    s = json.dumps(obj, indent=2, ensure_ascii=True, default=str)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(s)
    return s
