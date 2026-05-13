"""
CyberSec Pro Academy — Post-Deploy Regression Test
====================================================
Run this after every deploy_bat push to catch deploy-overwrite bugs
(like the 2026-04-19 Mailchimp form strip) before they cost signups.

Checks:
  1. All canonical pages return 200
  2. All internal links on key pages resolve (no 404s)
  3. Critical external links respond (Teachable, Mailchimp)
  4. Free guide PDF is still live and downloads
  5. Mailchimp list-manage snippet still wired into the signup form
     (checks home + free-resources pages for the u=/id= markers)

Exit code: 0 = all pass, 1 = any fail

Usage:
  Double-click regression_test.bat
  OR: python regression_test.py
  OR: python regression_test.py --base https://staging.example.com

No pip installs — pure stdlib. Writes an HTML report next to the script
and opens it automatically in a browser.
"""

import argparse
import datetime as dt
import html as htmlmod
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

# ---------------------------------------------------------------------------
# CONFIG — edit these lists when the site changes
# ---------------------------------------------------------------------------

DEFAULT_BASE = "https://cybersecproacademy.org"

# Canonical pages. Each entry is tried without .html first; on 404, the
# script retries with .html so it works whether Netlify rewrites or not.
PAGES = [
    "/",
    "/free-resources",
    "/checkout",
    "/welcome",
    "/labs",
    "/career-roadmap",
    "/quiz",
    "/price-comparison",
]

# Pages whose outbound links we crawl for 404s.
CRAWL_PAGES = [
    "/",
    "/free-resources",
    "/checkout",
]

# Free guide PDF path (the lead magnet).
PDF_PATH = "/Break_Into_Cybersecurity_Free_Guide_2026.pdf"

# Mailchimp integration markers — if any of these vanish, a deploy
# overwrite has stripped the form->Mailchimp hook (see 2026-04-19 incident).
MAILCHIMP_MARKERS = [
    "cybersecproacademy.us22.list-manage.com",
    "0ecc108bab8be2ee217833cd6",   # u= list id
    "5d6db48326",                   # id= audience id
]

# Pages to search for Mailchimp markers — at least ONE must contain all markers.
MAILCHIMP_CHECK_PAGES = [
    "/",
    "/free-resources",
]

# Critical external links that must respond. Anything < 400 = pass.
# All external checks are routed through fetch_external() which uses a
# browser User-Agent and always GETs (not HEAD), because short-link and
# checkout services (square.link, checkout.teachable.com/secure/, ...)
# return 403/404 to bot-like requests and produce false positives.
EXTERNAL_LINKS = [
    "https://cybersecurity-education.teachable.com/",
    ("https://cybersecproacademy.us22.list-manage.com/subscribe/post"
     "?u=0ecc108bab8be2ee217833cd6&id=5d6db48326"),
]

# Hosts we never want to try to crawl (analytics, CDN pixels, etc.).
SKIP_HOST_PATTERNS = [
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.com/tr",
    "clarity.ms",
    "doubleclick.net",
]

REQUEST_TIMEOUT = 15
USER_AGENT = "CyberSecPro-Regression/1.0 (+https://cybersecproacademy.org)"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_ctx = ssl.create_default_context()


def fetch(url, method="GET", timeout=REQUEST_TIMEOUT):
    """Return (status, headers_dict, body_bytes). status=0 on network error."""
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as resp:
            body = resp.read() if method == "GET" else b""
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers) if e.headers else {}, b""
    except Exception as e:
        return 0, {"__error__": str(e)}, b""


# Browser-ish UA for external checks. Short-link and checkout services
# (square.link, Teachable /secure/, etc.) routinely return 403/404 to
# non-browser User-Agents and reject HEAD entirely, producing false
# positives. We always GET externals with a browser UA to sidestep that.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/123.0.0.0 Safari/537.36")


def fetch_external(url, timeout=REQUEST_TIMEOUT):
    """GET an external URL with a browser UA. Returns (status, final_url).
    Follows redirects (urllib default). status=0 on network error."""
    req = urllib.request.Request(url, method="GET", headers={
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as resp:
            resp.read(1024)  # drain a little so the connection releases
            return resp.status, resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception:
        return 0, url


def smart_get(base, path):
    """GET path, falling back to path.html if we get a 404."""
    url = base + path
    status, headers, body = fetch(url)
    if status == 404 and not path.endswith(".html") and not path.endswith("/"):
        url2 = base + path + ".html"
        status2, headers2, body2 = fetch(url2)
        if 200 <= status2 < 400:
            return url2, status2, headers2, body2
    return url, status, headers, body


def smart_head(base, path):
    """HEAD first; fall back to GET if server rejects HEAD. Try .html on 404."""
    url = base + path
    status, headers, _ = fetch(url, method="HEAD")
    if status in (405, 501, 0):
        status, headers, _ = fetch(url, method="GET")
    if status == 404 and not path.endswith(".html") and not path.endswith("/"):
        url2 = base + path + ".html"
        status2, headers2, _ = fetch(url2, method="HEAD")
        if status2 in (405, 501, 0):
            status2, headers2, _ = fetch(url2, method="GET")
        if 200 <= status2 < 400:
            return url2, status2, headers2
    return url, status, headers


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

class Results:
    def __init__(self):
        self.rows = []  # list of dicts: category, name, ok, detail, url

    def add(self, category, name, ok, detail="", url=""):
        self.rows.append(dict(category=category, name=name, ok=ok, detail=detail, url=url))
        status = "PASS" if ok else "FAIL"
        tag = f"[{status}] {category}: {name}"
        if detail:
            tag += f"  ({detail})"
        print(tag)

    @property
    def total(self):
        return len(self.rows)

    @property
    def passed(self):
        return sum(1 for r in self.rows if r["ok"])

    @property
    def failed(self):
        return self.total - self.passed


def run_checks(base):
    r = Results()
    print("=" * 72)
    print("CyberSec Pro Academy — Regression Test")
    print(f"Base: {base}")
    print(f"Run:  {dt.datetime.now().isoformat(timespec='seconds')}")
    print("=" * 72)

    # -------- 1. pages ----------------------------------------------------
    print("\n-- Page availability --")
    page_bodies = {}  # path -> (final_url, body_text)
    for path in PAGES:
        final_url, status, headers, body = smart_get(base, path)
        ok = 200 <= status < 400
        detail = f"HTTP {status}"
        if not ok and "__error__" in headers:
            detail = headers["__error__"]
        r.add("Page", path, ok, detail, final_url)
        if ok:
            page_bodies[path] = (final_url, body.decode("utf-8", errors="ignore"))

    # -------- 2. free guide PDF ------------------------------------------
    print("\n-- Free guide PDF --")
    pdf_url = base + PDF_PATH
    status, headers, body = fetch(pdf_url)
    ct = headers.get("Content-Type", "").lower()
    is_pdf = body[:4] == b"%PDF" or "pdf" in ct
    size = len(body)
    r.add("PDF", "Free guide reachable", status == 200, f"HTTP {status}", pdf_url)
    r.add("PDF", "Content is a real PDF", is_pdf, f"magic={body[:4]!r}, type={ct}", pdf_url)
    r.add("PDF", "Size sanity (>10KB)", size > 10_000, f"{size} bytes", pdf_url)

    # -------- 3. Mailchimp integration -----------------------------------
    print("\n-- Signup form → Mailchimp --")
    marker_hit_anywhere = {m: False for m in MAILCHIMP_MARKERS}
    for path in MAILCHIMP_CHECK_PAGES:
        final_url, status, headers, body = smart_get(base, path)
        if not (200 <= status < 400):
            r.add("Mailchimp", f"page available for scan: {path}", False, f"HTTP {status}", final_url)
            continue
        text = body.decode("utf-8", errors="ignore")
        for marker in MAILCHIMP_MARKERS:
            if marker in text:
                marker_hit_anywhere[marker] = True
    for marker, hit in marker_hit_anywhere.items():
        short = marker if len(marker) <= 40 else marker[:37] + "..."
        r.add("Mailchimp", f"marker present somewhere: {short}", hit,
              "" if hit else "DEPLOY MAY HAVE STRIPPED THE MAILCHIMP HOOK")

    # -------- 4. internal link crawl -------------------------------------
    print("\n-- Internal link crawl --")
    link_re = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
    internal_links = set()
    external_links_found = set()
    for path in CRAWL_PAGES:
        if path not in page_bodies:
            continue
        _, text = page_bodies[path]
        for raw in link_re.findall(text):
            raw = raw.strip()
            if not raw:
                continue
            low = raw.lower()
            if (low.startswith("#") or low.startswith("mailto:") or
                    low.startswith("tel:") or low.startswith("javascript:") or
                    low.startswith("data:")):
                continue
            if raw.startswith("/") and not raw.startswith("//"):
                internal_links.add(raw.split("#")[0].split("?")[0])
            elif raw.startswith(base):
                tail = raw[len(base):] or "/"
                internal_links.add(tail.split("#")[0].split("?")[0])
            elif low.startswith("http://") or low.startswith("https://"):
                external_links_found.add(raw.split("#")[0])

    # Dedup: strip trailing slashes except root
    cleaned = set()
    for link in internal_links:
        if link != "/" and link.endswith("/"):
            link = link[:-1]
        cleaned.add(link)
    internal_links = sorted(cleaned)

    for link in internal_links:
        final_url, status, headers = smart_head(base, link)
        ok = 200 <= status < 400
        r.add("Link", link, ok, f"HTTP {status}", final_url)

    # -------- 5. critical external links ---------------------------------
    print("\n-- Critical external links --")
    for url in EXTERNAL_LINKS:
        status, _final = fetch_external(url)
        ok = 200 <= status < 400
        r.add("External", url, ok, f"HTTP {status}", url)

    # -------- 6. other external links found (informational) -------------
    print("\n-- Other external links (informational) --")
    for url in sorted(external_links_found):
        if any(pat in url for pat in SKIP_HOST_PATTERNS):
            continue
        if url in EXTERNAL_LINKS:
            continue
        status, _final = fetch_external(url)
        ok = 200 <= status < 400
        detail = f"HTTP {status}" if status else "network error"
        r.add("ExtRef", url, ok, detail, url)

    return r


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def write_html_report(results, base, path):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_cat = {}
    for row in results.rows:
        by_cat.setdefault(row["category"], []).append(row)

    def esc(s):
        return htmlmod.escape(str(s))

    sections = []
    def row_html(r):
        cls = "ok" if r["ok"] else "bad"
        status_txt = "PASS" if r["ok"] else "FAIL"
        link_cell = ""
        if r["url"]:
            link_cell = '<a href="' + esc(r["url"]) + '" target="_blank" rel="noopener">open</a>'
        return (
            f"<tr class='{cls}'>"
            f"<td>{status_txt}</td>"
            f"<td>{esc(r['name'])}</td>"
            f"<td>{esc(r['detail'])}</td>"
            f"<td>{link_cell}</td>"
            f"</tr>"
        )

    for cat, rows in by_cat.items():
        cat_pass = sum(1 for r in rows if r["ok"])
        body_rows = "\n".join(row_html(r) for r in rows)
        sections.append(f"""
        <section>
          <h2>{esc(cat)} <small>{cat_pass}/{len(rows)} passed</small></h2>
          <table>
            <thead><tr><th>Status</th><th>Check</th><th>Detail</th><th></th></tr></thead>
            <tbody>{body_rows}</tbody>
          </table>
        </section>""")

    overall_class = "ok" if results.failed == 0 else "bad"
    overall = "ALL PASS" if results.failed == 0 else f"{results.failed} FAILED"

    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>CyberSecPro Regression — {now}</title>
<style>
  body {{ font: 14px/1.45 -apple-system, Segoe UI, Roboto, Arial, sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ margin-bottom: 4px; }}
  .meta {{ color: #666; margin-bottom: 24px; }}
  .banner {{ padding: 14px 18px; border-radius: 8px; font-weight: 600; font-size: 18px; margin-bottom: 28px; }}
  .banner.ok {{ background: #e8f6ec; color: #1c6b2c; border: 1px solid #b8e0c2; }}
  .banner.bad {{ background: #fdeaea; color: #a2201a; border: 1px solid #f0b4b1; }}
  h2 {{ margin-top: 28px; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
  h2 small {{ color: #888; font-weight: 400; font-size: 13px; margin-left: 8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
  th {{ background: #fafafa; font-weight: 600; }}
  tr.ok td:first-child {{ color: #1c6b2c; font-weight: 600; }}
  tr.bad td:first-child {{ color: #a2201a; font-weight: 600; }}
  tr.bad td {{ background: #fdf3f3; }}
  code, a {{ word-break: break-all; }}
</style></head><body>
<h1>CyberSec Pro Academy — Regression Test</h1>
<div class="meta">Base: <code>{esc(base)}</code> &middot; Run: {now}</div>
<div class="banner {overall_class}">{overall} &middot; {results.passed}/{results.total} checks passed</div>
{"".join(sections)}
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help=f"Base URL (default: {DEFAULT_BASE})")
    ap.add_argument("--no-open", action="store_true",
                    help="Do not open the HTML report after the run")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    results = run_checks(base)

    print(chr(10) + "=" * 72)
    print(f"SUMMARY: {results.passed}/{results.total} passed, {results.failed} failed")
    print("=" * 72)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(script_dir, f"regression_report_{stamp}.html")
    write_html_report(results, base, report_path)
    print(chr(10) + "HTML report: " + report_path)

    if not args.no_open:
        try:
            import pathlib
            webbrowser.open(pathlib.Path(report_path).as_uri())
        except Exception:
            pass

    sys.exit(0 if results.failed == 0 else 1)


if __name__ == "__main__":
    main()
