"""Targeted desk-research URL discovery using a normal browser.

Requires: pip install -r requirements.txt
Run: python research_url_collector.py

This searches public search-engine result pages. It does NOT bypass CAPTCHAs,
login requirements, bot protection, or guarantee exhaustive site coverage.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlencode, urlsplit, urlunsplit, unquote

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# ========================= USER CONFIGURATION ==========================
KEYWORDS = ["网盘"]
WEBSITES = ["36kr.com"]

ENGINE = "google"            # "google" or "bing"
PAGES_PER_QUERY = 3           # maximum pages to inspect per keyword × website
MAX_RESULTS_PER_QUERY = 20    # maximum ranked organic results per search task
HEADLESS = False              # visible Chrome; easier to inspect failures
WAIT_SECONDS = 18             # load timeout per search-result page
REQUEST_DELAY_RANGE = (3.0, 6.0)  # courteous delay between queries
OUTPUT_DIR = Path("research_output")
# ======================================================================

LOG = logging.getLogger("research_url_collector")
RESULT_COLUMNS = ["keyword", "website", "search_engine", "search_query", "rank", "page", "title", "snippet", "url", "collected_at_utc"]
UNIQUE_COLUMNS = ["url", "website", "keywords", "best_rank", "titles", "snippets"]
TASK_COLUMNS = ["keyword", "website", "query", "status", "results_found", "pages_attempted", "error", "completed_at_utc"]
BLOCK_MARKERS = ("captcha", "unusual traffic", "verify you are human", "verify you're human", "automated queries", "our systems have detected unusual traffic", "security check")


@dataclass(frozen=True)
class Hit:
    url: str
    title: str
    snippet: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_domain(value: str) -> str:
    """Accept example.org or https://www.example.org/path; return example.org."""
    value = value.strip()
    if not value:
        raise ValueError("Website/domain cannot be empty")
    parsed = urlsplit(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ValueError(f"Invalid domain: {value!r}")
    return host


def belongs_to_domain(url: str, domain: str) -> bool:
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower().rstrip(".")
        return p.scheme.lower() in ("http", "https") and (host == domain or host.endswith("." + domain))
    except ValueError:
        return False


def canonical_url(url: str) -> str | None:
    """Conservative normalization; never erase potentially meaningful query params."""
    try:
        p = urlsplit(url.strip())
        if p.scheme.lower() not in ("http", "https") or not p.hostname:
            return None
        if p.username or p.password:
            return None
        host = p.hostname.lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        port = p.port
        netloc = host + (f":{port}" if port and not ((p.scheme == "http" and port == 80) or (p.scheme == "https" and port == 443)) else "")
        path = p.path or "/"
        if len(path) > 1:
            path = path.rstrip("/")
        # Remove only well-known click tracking params; other query params are retained.
        from urllib.parse import parse_qsl
        trackers = {"fbclid", "gclid", "msclkid", "igshid", "mc_cid", "mc_eid"}
        pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in trackers]
        query = urlencode(sorted(pairs), doseq=True)
        return urlunsplit((p.scheme.lower(), netloc, path, query, ""))
    except (ValueError, AttributeError):
        return None


def unwrap_search_url(url: str) -> str:
    """Handle common Google /url?q=... wrappers; keep other URLs unchanged."""
    p = urlsplit(url)
    if p.hostname in ("google.com", "www.google.com") and p.path == "/url":
        return parse_qs(p.query).get("q", [url])[0]
    return url


def search_url(engine: str, query: str, page: int) -> str:
    if engine == "bing":
        return "https://www.bing.com/search?" + urlencode({"q": query, "first": page * 10 + 1})
    if engine == "google":
        return "https://www.google.com/search?" + urlencode({"q": query, "start": page * 10, "num": 10})
    raise ValueError("ENGINE must be 'bing' or 'google'")


def selectors(engine: str) -> tuple[str, str, str]:
    if engine == "bing":
        return "li.b_algo", "h2 a[href]", ".b_caption p"
    return "div.MjjYud, div.g", "h3", ".VwiC3b"


def setup_browser(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1365,950")
    opts.add_argument("--lang=en-GB")
    # Selenium Manager (Selenium 4.6+) resolves chromedriver in ordinary installations.
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(WAIT_SECONDS)
    return driver


def detect_block(driver: webdriver.Chrome) -> bool:
    try:
        text = (driver.title + " " + driver.find_element(By.TAG_NAME, "body").text[:4000]).lower()
        return any(marker in text for marker in BLOCK_MARKERS)
    except WebDriverException:
        return False


def extract_hits(driver: webdriver.Chrome, engine: str) -> list[Hit]:
    """Extract results from visible organic-result containers, not all page links."""
    container_css, link_css, snippet_css = selectors(engine)
    hits = []
    for item in driver.find_elements(By.CSS_SELECTOR, container_css):
        try:
            if engine == "google":
                h3 = item.find_element(By.CSS_SELECTOR, link_css)
                anchor = h3.find_element(By.XPATH, "./ancestor::a[1]")
                title = h3.text.strip()
            else:
                anchor = item.find_element(By.CSS_SELECTOR, link_css)
                title = anchor.text.strip()
            url = unwrap_search_url(anchor.get_attribute("href") or "")
            if not url:
                continue
            snippets = item.find_elements(By.CSS_SELECTOR, snippet_css)
            snippet = snippets[0].text.strip() if snippets else ""
            hits.append(Hit(url, title, snippet))
        except WebDriverException:
            continue
    # Preserve displayed result order. De-duplication is done later at task level.
    return hits


def organic_rows(hits: list[Hit], *, keyword: str, website: str, engine: str,
                 query: str, page: int, start_rank: int, seen: set[str],
                 limit: int) -> list[dict]:
    """Convert displayed organic hits to ranked rows; preserve first occurrence."""
    rows = []
    for hit in hits:
        normalized = canonical_url(hit.url)
        if not normalized or not belongs_to_domain(normalized, website):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        rows.append({"keyword": keyword, "website": website,
                     "search_engine": engine, "search_query": query,
                     "rank": start_rank + len(rows), "page": page + 1,
                     "title": hit.title, "snippet": hit.snippet,
                     "url": normalized, "collected_at_utc": utc_now()})
        if len(rows) >= limit:
            break
    return rows


def atomic_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    temp.replace(path)


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        f.flush()


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                if line.strip():
                    rows.append(json.loads(line))
            except json.JSONDecodeError:
                LOG.warning("Skipping truncated checkpoint line")
    return rows


def export(output_dir: Path, rows: list[dict], tasks: list[dict]) -> None:
    """Preserve task order and original rank; export separate cross-task dedup view."""
    atomic_csv(output_dir / "results_ranked.csv", rows, RESULT_COLUMNS)
    atomic_csv(output_dir / "tasks.csv", tasks, TASK_COLUMNS)
    unique = {}
    for row in rows:
        key = row["url"]
        if key not in unique:
            unique[key] = {"url": key, "website": row["website"],
                           "keywords": [], "best_rank": row["rank"],
                           "titles": [], "snippets": []}
        item = unique[key]
        item["best_rank"] = min(item["best_rank"], row["rank"])
        for col, value in (("keywords", row["keyword"]), ("titles", row["title"]),
                           ("snippets", row["snippet"])):
            if value and value not in item[col]:
                item[col].append(value)
    unique_rows = []
    for item in unique.values():
        record = dict(item)
        for col in ("keywords", "titles", "snippets"):
            record[col] = " | ".join(record[col])
        unique_rows.append(record)
    atomic_csv(output_dir / "urls_unique.csv", unique_rows, UNIQUE_COLUMNS)
    (output_dir / "urls.txt").write_text(
        "\n".join(item["url"] for item in unique_rows)
        + ("\n" if unique_rows else ""), encoding="utf-8")


def collect_urls(keywords: list[str], websites: list[str], *, engine: str = ENGINE,
                 pages_per_query: int = PAGES_PER_QUERY,
                 max_results_per_query: int = MAX_RESULTS_PER_QUERY,
                 output_dir: Path = OUTPUT_DIR, headless: bool = HEADLESS,
                 delay_range: tuple[float, float] = REQUEST_DELAY_RANGE,
                 driver_factory=None) -> list[dict]:
    """Collect Google's/Bing's displayed organic results per query, preserving rank.

    Results reflect the captured search pages, not guaranteed global search ranks.
    A task completes only if pagination ends naturally or requested N is reached.
    """
    if engine not in ("bing", "google"):
        raise ValueError("engine must be 'bing' or 'google'")
    if pages_per_query < 1 or max_results_per_query < 1:
        raise ValueError("pages_per_query and max_results_per_query must be >= 1")
    if len(delay_range) != 2 or not 0 <= delay_range[0] <= delay_range[1]:
        raise ValueError("delay_range must contain two ordered nonnegative numbers")
    domains = list(dict.fromkeys(clean_domain(d) for d in websites))
    terms = list(dict.fromkeys(k.strip() for k in keywords if isinstance(k, str) and k.strip()))
    if not domains or not terms:
        raise ValueError("At least one keyword and one website are required")
    run_spec = {"keywords": terms, "websites": domains, "engine": engine,
                "pages": pages_per_query, "max": max_results_per_query, "query_style": "unquoted_v2"}
    run_id = hashlib.sha256(json.dumps(run_spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    folder = Path(output_dir) / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps(run_spec, ensure_ascii=False, indent=2), encoding="utf-8")
    hits_path, task_path = folder / "ranked_hits.jsonl", folder / "tasks.jsonl"
    tasks = load_jsonl(task_path)
    # Only commit rows associated with a successful task; failed task partial pages are retried.
    committed = {t["query"] for t in tasks if t.get("status") == "success"}
    rows = [r for r in load_jsonl(hits_path) if r.get("search_query") in committed]
    planned = [(k, d, f"{k} site:{d}") for k in terms for d in domains]
    todo = [(k, d, q) for k, d, q in planned if q not in committed]
    if not todo:
        export(folder, rows, tasks)
        return rows
    driver = (driver_factory or (lambda: setup_browser(headless)))()
    try:
        for keyword, domain, query in todo:
            task_rows: list[dict] = []
            seen: set[str] = set()
            pages_attempted = 0
            status, error = "success", ""
            blocked = False
            try:
                for page in range(pages_per_query):
                    pages_attempted += 1
                    LOG.info("Searching %s: %s, page %s", engine, query, page + 1)
                    try:
                        driver.get(search_url(engine, query, page))
                    except TimeoutException as exc:
                        raise RuntimeError("Search page timed out") from exc
                    if detect_block(driver):
                        blocked = True
                        raise RuntimeError("CAPTCHA/bot protection detected; stopped")
                    container_css, _, _ = selectors(engine)
                    try:
                        WebDriverWait(driver, WAIT_SECONDS).until(
                            lambda d: d.find_elements(By.CSS_SELECTOR, container_css)
                            or "no results" in d.page_source.lower() or detect_block(d))
                    except TimeoutException as exc:
                        raise RuntimeError("No results extracted: layout/consent/timeout") from exc
                    if detect_block(driver):
                        blocked = True
                        raise RuntimeError("CAPTCHA/bot protection detected; stopped")
                    candidates = extract_hits(driver, engine)
                    if not candidates:
                        if "no results" in driver.page_source.lower():
                            break
                        raise RuntimeError("No organic results parsed; markup may have changed")
                    new_rows = organic_rows(candidates, keyword=keyword, website=domain,
                                            engine=engine, query=query, page=page,
                                            start_rank=len(task_rows) + 1, seen=seen,
                                            limit=max_results_per_query - len(task_rows))
                    task_rows.extend(new_rows)
                    if len(task_rows) >= max_results_per_query:
                        break
                    if page + 1 < pages_per_query:
                        time.sleep(random.uniform(*delay_range))
            except (RuntimeError, WebDriverException) as exc:
                status, error = "failed", str(exc)[:500]
                LOG.warning("Query failed %s: %s", query, error)
            task = {"keyword": keyword, "website": domain, "query": query,
                    "status": status, "results_found": len(task_rows),
                    "pages_attempted": pages_attempted, "error": error,
                    "completed_at_utc": utc_now()}
            # Persist rows before success flag; on interrupted writes, uncommitted rows are ignored.
            if status == "success":
                for row in task_rows:
                    append_jsonl(hits_path, row)
                rows.extend(task_rows)
            append_jsonl(task_path, task)
            tasks.append(task)
            export(folder, rows, tasks)
            if blocked:
                break
            if (keyword, domain, query) != todo[-1]:
                time.sleep(random.uniform(*delay_range))
    finally:
        driver.quit()
        export(folder, rows, tasks)
    LOG.info("Collected %d ranked results; %s", len(rows), folder)
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    collect_urls(KEYWORDS, WEBSITES)
