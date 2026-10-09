#!/usr/bin/env python3
"""Inspect the actual old developer website (NOT nash.dom.ru or progress.json).

Writes public metadata only; no credentials, no imports and no arbitrary
classification of plans/renders as construction photographs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

SITE = "https://xn--102-qddaexafvn7b5i.xn--p1ai"
IMAGE_EXT = re.compile(r"\.(?:jpg|jpeg|png|webp)(?:$|\?)", re.I)
ASSET_RE = re.compile(r"""[/"']((?:assets|images|uploads)/[^"'<>\\\s]+\.(?:png|jpe?g|webp))""", re.I)
MONTH_RE = re.compile(
    r"(январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\s+20\d{2}",
    re.I,
)


def clean_link(value: str, page_url: str) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().strip('"').strip("'")
    if not value or value.startswith(("data:", "javascript:", "#")):
        return None
    result = urljoin(page_url, value)
    parsed = urlparse(result)
    if parsed.hostname != urlparse(SITE).hostname or not IMAGE_EXT.search(parsed.path):
        return None
    return urlunparse(parsed._replace(fragment=""))


def extract_inventory(html: str, page_url: str):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    attributes = ("src", "data-src", "data-original", "data-full", "data-full-src",
                  "data-image", "data-zoom-image", "data-large", "data-lazy-src", "href")
    for element in soup.find_all(True):
        for attr in attributes:
            value = element.get(attr)
            if not isinstance(value, str):
                continue
            link = clean_link(value, page_url)
            if not link:
                continue
            surrounding = element
            context = ""
            for _ in range(4):
                if surrounding is None:
                    break
                candidate = surrounding.get_text(" ", strip=True)[:250]
                if MONTH_RE.search(candidate):
                    context = candidate
                    break
                surrounding = surrounding.parent
            found.setdefault(link, {"url": link, "context": context,
                                    "month": MONTH_RE.search(context).group(0) if MONTH_RE.search(context) else None,
                                    "tag": element.name})
        srcset = element.get("srcset") or element.get("data-srcset")
        if isinstance(srcset, str):
            for value in srcset.split(","):
                link = clean_link(value.strip().split(" ")[0], page_url)
                if link:
                    found.setdefault(link, {"url": link, "context": "", "month": None, "tag": "srcset"})
    # Captures assets referenced in inline JSON/JS, without assuming their category.
    for match in ASSET_RE.finditer(html):
        link = clean_link("/" + match.group(1).lstrip("/"), page_url)
        if link:
            found.setdefault(link, {"url": link, "context": "", "month": None, "tag": "html"})
    text = soup.get_text(" ", strip=True)
    section_mentions = [word for word in ("Ход строительства", "Фотографии", "Фотоотчёт",
                                          "Галерея", "Планировки")
                        if word.casefold() in text.casefold()]
    months = sorted({match.group(0) for match in MONTH_RE.finditer(text)})
    items = list(found.values())
    return {
        "page_title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "image_count": len(items),
        "month_labeled_images": sum(bool(x["month"]) for x in items),
        "text_months": months,
        "section_mentions": section_mentions,
        "images": items[:150],
        "truncated": len(items) > 150,
    }


def run(output: Path):
    report = {
        "source": SITE,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "warning": "Discovery only. Images have NOT been downloaded or imported.",
        "units": {},
    }
    session = requests.Session()
    session.headers["User-Agent"] = "ConstructionProgressArchiver/1.0 (+owned developer website)"
    for unit in range(1, 9):
        url = SITE + f"/complex/milovskii-selsovet-liter-{unit}"
        try:
            response = session.get(url, timeout=25)
            entry = {"page_url": url, "http_status": response.status_code}
            if response.ok:
                entry.update(extract_inventory(response.text, response.url))
            else:
                entry["error"] = "HTTP " + str(response.status_code)
        except requests.RequestException as exc:
            entry = {"page_url": url, "error": type(exc).__name__ + ": " + str(exc)[:180]}
        report["units"][f"Литер {unit}"] = entry
        print(f"Литер {unit}: status={entry.get('http_status')} assets={entry.get('image_count', 0)} months={entry.get('month_labeled_images', 0)} error={entry.get('error', '-')}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    run(Path("_site/legacy-site-report.json"))
