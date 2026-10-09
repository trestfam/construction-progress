#!/usr/bin/env python3
"""Monthly Yandex Disk construction photographs -> GitHub Pages."""
from __future__ import annotations
import hashlib
import io
import json
import logging
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

LOG = logging.getLogger("progress")
API = "https://cloud-api.yandex.net/v1/disk/resources"
ROOT = "app:/"  # Root of the OAuth application folder (already named Ход строительства)
START = "2026-10"
BASE_URL = "https://trestfam.github.io/construction-progress"
MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SITE_BYTES = 750_000_000


def month_limit(today: date) -> str:
    y, m = today.year, today.month
    if today.day < 27:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


def normalize_month(name: str) -> str | None:
    """Accept Russian month-year names and existing ISO folder names."""
    name = name.strip()
    if re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", name):
        return name
    match = re.fullmatch(r"([А-Яа-яЁё]+)\s+(20\d\d)", name)
    if match:
        number = next((i for i, title in enumerate(MONTHS, 1)
                       if title.casefold() == match.group(1).casefold()), None)
        if number:
            return f"{match.group(2)}-{number:02d}"
    return None


def eligible(month: str, today: date) -> bool:
    canonical = normalize_month(month)
    return canonical is not None and START <= canonical <= month_limit(today)


def disk_path(*parts: str) -> str:
    return ROOT + "/".join(parts) if parts else ROOT


def label_month(month: str) -> str:
    return f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}"


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def archive_path(project: dict, unit: str, month: str) -> str:
    return disk_path(project["folder"], "Готовые фотографии",
                     f'{project["folder"]}. {unit}. {label_month(month)}')


class Disk:
    def __init__(self, token: str):
        if not token:
            raise RuntimeError("Missing YANDEX_DISK_TOKEN GitHub Actions secret")
        self.session = requests.Session()
        self.session.headers["Authorization"] = "OAuth " + token

    def request(self, method, url, *, params=None, data=None, direct=False):
        for attempt in range(5):
            try:
                client = requests if direct else self.session
                response = client.request(method, url, params=params, data=data, timeout=(15, 120))
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                if response.status_code == 404 and not direct:
                    return None
                response.raise_for_status()
                return response
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Yandex API retry limit exceeded")

    def api(self, method, suffix="", **params):
        response = self.request(method, API + suffix, params=params)
        return None if response is None else response.json()

    def stat(self, path):
        return self.api("GET", path=path)

    def list(self, path):
        items, offset = [], 0
        while True:
            response = self.api("GET", path=path, limit=1000, offset=offset)
            if response is None:
                return None
            emb = response.get("_embedded", {})
            batch = emb.get("items", [])
            items.extend(batch)
            offset += len(batch)
            if not batch or offset >= emb.get("total", 0):
                return items

    def mkdir(self, path):
        existing = self.stat(path)
        if existing:
            if existing["type"] != "dir":
                raise ValueError("Not a directory: " + path)
            return
        response = self.request("PUT", API, params={"path": path})
        if response is None:
            raise RuntimeError("Unable to create directory " + path)

    def download(self, path):
        data = self.api("GET", "/download", path=path)
        if data is None:
            raise FileNotFoundError(path)
        return self.request("GET", data["href"], direct=True).content

    def upload(self, path, content):
        data = self.api("GET", "/upload", path=path, overwrite="true")
        if data is None:
            raise RuntimeError("Cannot get upload URL for " + path)
        self.request("PUT", data["href"], data=content, direct=True)


def render(data: bytes, project: str, unit: str, month: str, for_site: bool) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as original:
            picture = ImageOps.exif_transpose(original).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError("Invalid image") from exc
    if min(picture.size) < 250:
        raise ValueError("Image smaller than 250px")
    picture.thumbnail((1800, 1800) if for_site else (2560, 2560), Image.Resampling.LANCZOS)
    if for_site:
        w, h = picture.size
        text1 = f"ЖК «{project.upper()}» · {unit.upper()}"
        text2 = label_month(month).upper()
        draw = ImageDraw.Draw(picture, "RGBA")
        pad = max(9, min(w, h) // 50)
        fontfile = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not Path(fontfile).exists():
            raise RuntimeError("Expected DejaVu font missing")
        font_size = max(10, min(42, w // 30))
        for size in range(font_size, 8, -1):
            f1 = ImageFont.truetype(fontfile, size)
            f2 = ImageFont.truetype(fontfile, max(9, int(size * .76)))
            tw = max(draw.textbbox((0, 0), text1, font=f1)[2],
                     draw.textbbox((0, 0), text2, font=f2)[2])
            if tw + 4 * pad <= w:
                break
        height = max(40, int(size * 3 + pad * 2))
        left, top = pad, max(0, h - height - pad)
        draw.rounded_rectangle((left, top, min(w, left + tw + 2 * pad), h - pad),
                               radius=max(5, pad // 2), fill=(0, 0, 0, 165))
        draw.text((left + pad, top + pad // 2), text1, font=f1, fill="white")
        draw.text((left + pad, top + pad // 2 + int(size * 1.5)), text2,
                  font=f2, fill="white")
    result = io.BytesIO()
    picture.save(result, format="JPEG", quality=83 if for_site else 92,
                 optimize=True, progressive=True)
    return result.getvalue()


def process_unit(disk, project, unit, today):
    base = disk_path(project["folder"], "Исходные фотографии", unit)
    for folder in sorted(disk.list(base) or [], key=lambda f: f["name"]):
        month = normalize_month(folder["name"])
        if folder["type"] != "dir" or month is None or not eligible(month, today):
            continue
        dest = archive_path(project, unit, month)
        manifest_path = dest + "/_manifest.json"
        if disk.stat(manifest_path):
            LOG.info("Already completed: %s / %s / %s", project["slug"], unit, month)
            continue
        source = base + "/" + folder["name"]
        files = disk.list(source) or []
        if not any(f["name"] == "_READY.txt" and f["type"] == "file" for f in files):
            LOG.info("Waiting for _READY.txt: %s", source)
            continue
        photos = sorted((f for f in files if f["type"] == "file" and
                         Path(f["name"]).suffix.lower() in EXTS), key=lambda f: f["name"])
        if not photos:
            LOG.warning("Ready folder without photos: %s", source)
            continue
        disk.mkdir(disk_path(project["folder"], "Готовые фотографии"))
        disk.mkdir(dest)
        done = []
        for photo in photos:
            raw = disk.download(source + "/" + photo["name"])
            digest = hashlib.md5(raw).hexdigest()
            if photo.get("md5") and photo["md5"].lower() != digest:
                raise ValueError("Source changed while downloading: " + photo["name"])
            stem = short_hash(photo["name"])
            site_name, eis_name = stem + "-site.jpg", stem + "-eis.jpg"
            disk.upload(dest + "/" + site_name,
                        render(raw, project["name"], unit, month, True))
            disk.upload(dest + "/" + eis_name,
                        render(raw, project["name"], unit, month, False))
            done.append({"source_name": photo["name"], "site_file": site_name,
                         "eis_file": eis_name, "source_md5": digest})
        manifest = {"schema": 1, "status": "complete", "project": project["slug"],
                    "unit": unit, "month": month, "photos": done}
        # Commit marker LAST; retried runs overwrite deterministic filenames.
        disk.upload(manifest_path, json.dumps(manifest, ensure_ascii=False).encode())
        LOG.info("Completed: %s / %s / %s: %d photos",
                 project["slug"], unit, month, len(done))


def export_site(disk, projects, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    total = 0
    for project in projects:
        entries = []
        base = disk_path(project["folder"], "Готовые фотографии")
        for directory in disk.list(base) or []:
            if directory["type"] != "dir":
                continue
            folder = base + "/" + directory["name"]
            if not disk.stat(folder + "/_manifest.json"):
                continue
            manifest = json.loads(disk.download(folder + "/_manifest.json").decode("utf-8"))
            if manifest.get("status") != "complete" or manifest.get("project") != project["slug"]:
                continue
            month, unit = manifest["month"], manifest["unit"]
            if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month):
                raise ValueError("Invalid month in manifest")
            photos = []
            for photo in manifest["photos"]:
                name = photo["site_file"]
                if not re.fullmatch(r"[0-9a-f]{20}-site\.jpg", name):
                    raise ValueError("Invalid output filename")
                rel = f'images/{project["slug"]}/{short_hash(unit)}/{month}/{name}'
                data = disk.download(folder + "/" + name)
                total += len(data)
                if total > MAX_SITE_BYTES:
                    raise RuntimeError("Photo archive exceeds configured Pages safety limit")
                target = output / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                photos.append({"url": BASE_URL + "/" + quote(rel), "source": photo["source_name"]})
            entries.append({"unit": unit, "month": month,
                            "title": label_month(month), "photos": photos})
        entries.sort(key=lambda x: (x["month"], x["unit"]), reverse=True)
        (output / f'{project["slug"]}.json').write_text(
            json.dumps({"version": 1, "project": project["name"], "entries": entries},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "index.html").write_text(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Ход строительства</title><h1>ГК «Семейный трест»</h1></html>',
        encoding="utf-8")
    (output / ".nojekyll").touch()
    LOG.info("Pages image bytes: %d", total)


def run(disk, projects, today, output):
    disk.mkdir(ROOT)
    failures = []
    for project in projects:
        root = disk_path(project["folder"], "Исходные фотографии")
        for path in (disk_path(project["folder"]), root,
                     disk_path(project["folder"], "Готовые фотографии")):
            disk.mkdir(path)
        for unit in project.get("initial_units", []):
            disk.mkdir(root + "/" + unit)
        for unit in disk.list(root) or []:
            if unit["type"] != "dir":
                continue
            try:
                # Create current month's folder even before the 27th.
                this_month = f"{today.year:04d}-{today.month:02d}"
                if this_month >= START:
                    # Keep the month folder in both source and finished-photo trees.
                    # An empty destination is NOT a completed month; only _manifest.json is.
                    disk.mkdir(root + "/" + unit["name"] + "/" + label_month(this_month))
                    disk.mkdir(archive_path(project, unit["name"], this_month))
                process_unit(disk, project, unit["name"], today)
            except Exception:
                LOG.exception("Processing failed: %s / %s", project["slug"], unit["name"])
                failures.append(project["slug"] + "/" + unit["name"])
    export_site(disk, projects, output)
    if failures:
        raise RuntimeError("Incomplete units (will retry): " + ", ".join(failures))


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    today = (date.fromisoformat(os.environ["RUN_DATE"]) if os.getenv("RUN_DATE") else
             datetime.now(ZoneInfo("Asia/Yekaterinburg")).date())
    projects = json.loads(Path("config/projects.json").read_text(encoding="utf-8"))["projects"]
    run(Disk(os.getenv("YANDEX_DISK_TOKEN", "")), projects, today, Path("_site"))


if __name__ == "__main__":
    main()
