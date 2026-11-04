#!/usr/bin/env python3
"""Handover Desk: deterministic pre-delivery checks for a live site, from its URL only.

Same input, same findings. No browser, no credentials, standard library only.
The browser walk (console errors, empty states) is the auditor agent's job, on top of this.

Usage:
  python3 audit/audit.py https://example.com            # Markdown report
  python3 audit/audit.py https://example.com --json     # JSON for the agent
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from html.parser import HTMLParser

USER_AGENT = "handover-desk-audit/0.1 (+https://github.com/rasarafi/handover-desk)"
TIMEOUT = 10

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
CHECK_INFO = {
    "alive": ("critical", "Site is not reachable"),
    "test-data": ("high", "Test accounts or fake people are visible"),
    "placeholder-text": ("high", "Placeholder text is still on the page"),
    "dev-url": ("high", "Development or staging URLs in shipped code"),
    "broken-link": ("high", "Broken link"),
    "metadata": ("low", "Missing or placeholder page metadata"),
}
CHECK_ORDER = list(CHECK_INFO)

PLACEHOLDER_TITLES = {
    "", "untitled", "document", "vite app", "react app", "create next app", "next app",
    "my app", "new page", "index", "home page", "title", "page title", "welcome to nginx!",
}
PLACEHOLDER_TEXT = re.compile(r"lorem ipsum|dolor sit amet|\binsert [\w ]{1,30} here\b|\{\{\s*\w+\s*\}\}", re.I)
FAKE_NAMES = re.compile(r"\b(John Doe|Jane Doe|Test User|Test Account|Foo Bar)\b", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
FAKE_LOCALS = {"test", "testing", "tester", "foo", "bar", "asdf", "demo", "dummy", "fake", "qwerty", "example", "user"}
FAKE_DOMAINS = {"test.com", "example.com", "example.org", "example.net", "mailinator.com", "test.test", "email.com"}
FAKE_TLDS = (".test", ".example", ".invalid", ".localhost")
URL_IN_TEXT = re.compile(r"""https?://[^\s"'`<>()\\]+""")
DEV_HOSTS = {"localhost", "0.0.0.0", "127.0.0.1", "::1"}
DEV_LABELS = {"staging", "stage", "dev", "uat", "preview", "qa", "sandbox"}
DEV_SUFFIXES = (".local", ".test", ".internal", ".localhost")


# ---------- small pure helpers (unit-tested) ----------

def find_test_data(text: str) -> list[str]:
    hits: list[str] = []
    for m in EMAIL.finditer(text):
        email = m.group(0)
        local, _, domain = email.lower().partition("@")
        if (
            local in FAKE_LOCALS
            or local.startswith("test")
            or domain in FAKE_DOMAINS
            or domain.endswith(FAKE_TLDS)
        ):
            hits.append(email)
    hits += [m.group(0) for m in FAKE_NAMES.finditer(text)]
    return list(OrderedDict.fromkeys(hits))


def _is_dev_host(host: str) -> bool:
    host = host.lower().strip("[]")
    if host in DEV_HOSTS or host.endswith(DEV_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        pass
    labels = host.split(".")
    return len(labels) > 2 and any(l in DEV_LABELS or l.startswith("staging") for l in labels[:-2])


def find_dev_urls(text: str, own_netloc: str) -> list[str]:
    hits = []
    for m in URL_IN_TEXT.finditer(text):
        url = m.group(0).rstrip(".,;:")
        parts = urllib.parse.urlsplit(url)
        if not parts.hostname or parts.netloc.lower() == own_netloc.lower():
            continue
        if _is_dev_host(parts.hostname):
            hits.append(url)
    return list(OrderedDict.fromkeys(hits))


def _snippet(text: str, start: int, end: int, pad: int = 50) -> str:
    s = text[max(0, start - pad): end + pad]
    s = " ".join(s.split())
    return ("…" if start > pad else "") + s + ("…" if end + pad < len(text) else "")


# ---------- fetching and parsing ----------

class Fetched:
    def __init__(self, url, status=None, ctype="", body=b"", error=None):
        self.url, self.status, self.ctype, self.body, self.error = url, status, ctype, body, error

    @property
    def ok(self):
        return self.error is None and self.status is not None and self.status < 400

    @property
    def text(self):
        return self.body.decode("utf-8", errors="replace")

    def describe(self):
        return self.error or f"HTTP {self.status}"


def fetch(url: str, method: str = "GET") -> Fetched:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            body = r.read(5_000_000) if method == "GET" else b""
            return Fetched(r.geturl(), r.status, r.headers.get("Content-Type", ""), body)
    except urllib.error.HTTPError as e:
        return Fetched(url, e.code, e.headers.get("Content-Type", "") if e.headers else "")
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return Fetched(url, error=f"TLS certificate problem: {reason.verify_message}")
        return Fetched(url, error=f"unreachable: {reason}")
    except (TimeoutError, OSError) as e:
        return Fetched(url, error=f"unreachable: {e}")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self._skip = 0
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.styles: list[str] = []
        self.icons: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
            self.title = ""
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
            if a["href"].lower().startswith("mailto:"):
                self.text_parts.append(" " + a["href"][7:].split("?")[0] + " ")
        elif tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            if "icon" in rel and a.get("href"):
                self.icons.append(a["href"])
            if "stylesheet" in rel and a.get("href"):
                self.styles.append(a["href"])
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.text_parts.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.text_parts).split())


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (pa.scheme, pa.netloc.lower()) == (pb.scheme, pb.netloc.lower())


def _short(url: str, base: str) -> str:
    p = urllib.parse.urlsplit(url)
    if _same_origin(url, base):
        return (p.path or "/") + (f"?{p.query}" if p.query else "")
    return url


# ---------- the audit ----------

def run(start_url: str, max_pages: int = 25, check_external: bool = True) -> dict:
    found: dict[str, list[dict]] = {c: [] for c in CHECK_ORDER}
    broken: "OrderedDict[str, dict]" = OrderedDict()
    report = {
        "url": start_url,
        "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "pages_checked": 0,
        "findings": [],
    }
    own = urllib.parse.urlsplit(start_url)

    first = fetch(start_url)
    if not first.ok:
        found["alive"].append({"page": start_url, "evidence": first.describe()})
        return _finish(report, found, broken, start_url)
    if own.scheme == "http" and not _is_dev_host(own.hostname or ""):
        found["alive"].append({"page": start_url, "evidence": "served over plain HTTP, not HTTPS"})

    queue, seen_urls, seen_bodies = [first.url], {first.url}, set()
    prefetched = {first.url: first}
    link_status: dict[str, Fetched] = {}
    assets_scanned: set[str] = set()
    pages: list[tuple[str, Page]] = []
    referrers: dict[str, list[str]] = {}

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        res = prefetched.pop(url, None) or fetch(url)
        link_status[url] = res
        if not res.ok or "html" not in res.ctype.lower():
            continue
        digest = hashlib.sha256(res.body).hexdigest()
        if digest in seen_bodies:
            continue
        seen_bodies.add(digest)
        page = Page()
        page.feed(res.text)
        pages.append((url, page))
        name = _short(url, start_url)
        html = res.text

        # visible text checks
        text = page.text
        for m in PLACEHOLDER_TEXT.finditer(text):
            found["placeholder-text"].append({"page": name, "evidence": _snippet(text, m.start(), m.end())})
            break
        fakes = find_test_data(text)
        if fakes:
            found["test-data"].append({"page": name, "evidence": ", ".join(fakes)})

        # dev URLs in the HTML itself, then in each same-origin script/stylesheet
        for hit in find_dev_urls(html, own.netloc):
            found["dev-url"].append({"page": name, "evidence": hit})
        for src in page.scripts + page.styles:
            asset = urllib.parse.urljoin(url, src)
            if not _same_origin(asset, start_url) or asset in assets_scanned:
                continue
            assets_scanned.add(asset)
            ar = fetch(asset)
            if not ar.ok:
                broken.setdefault(asset, {"status": ar.describe(), "pages": []})["pages"].append(name)
                continue
            for hit in find_dev_urls(ar.text, own.netloc):
                found["dev-url"].append({"page": _short(asset, start_url), "evidence": hit})

        # metadata
        title = (page.title or "").strip()
        if title.lower() in PLACEHOLDER_TITLES:
            found["metadata"].append({"page": name, "evidence": f'page title is "{title}"' if title else "page has no <title>"})
        for icon in page.icons:
            iu = urllib.parse.urljoin(url, icon)
            if iu not in link_status:
                link_status[iu] = fetch(iu)
            if not link_status[iu].ok:
                broken.setdefault(iu, {"status": link_status[iu].describe(), "pages": []})["pages"].append(name)

        # links: queue same-origin pages, check the rest
        for href in page.links:
            if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                continue
            target = urllib.parse.urldefrag(urllib.parse.urljoin(url, href))[0]
            if _same_origin(target, start_url):
                if target not in seen_urls:
                    seen_urls.add(target)
                    queue.append(target)
                    link_status[target] = None  # filled when crawled
                continue
            if not check_external or urllib.parse.urlsplit(target).scheme not in ("http", "https"):
                continue
            if target not in link_status:
                r = fetch(target, "HEAD")
                if r.status in (405, 501) or (r.status and r.status >= 400 and r.status not in (403, 429)):
                    r = fetch(target)
                link_status[target] = r
            r = link_status[target]
            if r.error or (r.status and r.status >= 400 and r.status not in (403, 429)):
                broken.setdefault(target, {"status": r.describe(), "pages": []})["pages"].append(name)

        # remember which pages link to which same-origin targets
        for href in page.links:
            target = urllib.parse.urldefrag(urllib.parse.urljoin(url, href))[0]
            if _same_origin(target, start_url):
                referrers.setdefault(target, []).append(name)

    # same-origin links that turned out broken
    for target, res in link_status.items():
        if res is None:
            res = fetch(target)
        if _same_origin(target, start_url) and not res.ok and target not in broken:
            refs = list(OrderedDict.fromkeys(referrers.get(target, [])))
            if refs:
                broken[target] = {"status": res.describe(), "pages": refs}

    # site-wide metadata
    if pages:
        first_url, first_page = pages[0]
        missing_og = [k for k in ("og:title", "og:image") if not first_page.meta.get(k)]
        if missing_og:
            found["metadata"].append({"page": _short(first_url, start_url), "evidence": "no " + ", ".join(missing_og) + " (link previews will be blank)"})
        if not any(p.icons for _, p in pages):
            fav = fetch(urllib.parse.urljoin(start_url, "/favicon.ico"))
            if not fav.ok:
                found["metadata"].append({"page": "(site)", "evidence": "no favicon: no <link rel=icon> and /favicon.ico is " + fav.describe()})

    report["pages_checked"] = len(pages)
    return _finish(report, found, broken, start_url)



def _finish(report, found, broken, start_url):
    findings = []
    for check in CHECK_ORDER:
        if check == "broken-link":
            for target, info in broken.items():
                pages = list(OrderedDict.fromkeys(info["pages"]))
                findings.append({
                    "check": "broken-link",
                    "severity": CHECK_INFO["broken-link"][0],
                    "title": f"Broken link: {_short(target, start_url)}",
                    "locations": [{"page": p, "evidence": f"{_short(target, start_url)} → {info['status']}"} for p in pages],
                })
        elif found[check]:
            sev, title = CHECK_INFO[check]
            findings.append({"check": check, "severity": sev, "title": title, "locations": found[check]})
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], CHECK_ORDER.index(f["check"])))
    for i, f in enumerate(findings, 1):
        f["id"] = i
    report["findings"] = findings
    return report


def to_markdown(report: dict) -> str:
    lines = [
        f"## Handover audit: {report['url']}",
        f"Checked {report['checked_at']} · {report['pages_checked']} page(s) · {len(report['findings'])} finding(s)",
        "",
    ]
    if not report["findings"]:
        lines.append("No problems found by the automatic checks.")
    for f in report["findings"]:
        lines.append(f"{f['id']}. **{f['title']}** ({f['severity']})")
        for loc in f["locations"]:
            lines.append(f"   - `{loc['page']}`: {loc['evidence']}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("url")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--max-pages", type=int, default=25)
    ap.add_argument("--no-external", action="store_true", help="skip checking links to other sites")
    args = ap.parse_args(argv)
    report = run(args.url, max_pages=args.max_pages, check_external=not args.no_external)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else to_markdown(report), end="")
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
