import unittest
import tempfile
import json
from pathlib import Path
from datetime import date
from scripts.progress import eligible, month_limit, label_month, disk_path, normalize_month, archive_path, legacy_archive_path, export_site, process_unit, run

class ProgressTests(unittest.TestCase):
    def test_start_day(self):
        self.assertEqual(month_limit(date(2026, 10, 26)), '2026-09')
        self.assertEqual(month_limit(date(2026, 10, 27)), '2026-10')
        self.assertEqual(month_limit(date(2026, 11, 1)), '2026-10')

    def test_month_eligibility(self):
        self.assertTrue(eligible('2026-10', date(2026, 11, 1)))
        self.assertFalse(eligible('2026-11', date(2026, 11, 1)))
        self.assertFalse(eligible('2026-09', date(2026, 10, 31)))

    def test_format(self):
        self.assertEqual(label_month('2026-10'), 'Октябрь 2026')
        self.assertEqual(disk_path('Атмосфера'), 'app:/Атмосфера')
        self.assertEqual(disk_path(), 'app:/')
        self.assertEqual(normalize_month('Октябрь 2026'), '2026-10')
        self.assertEqual(normalize_month('2026-10'), '2026-10')
        self.assertIsNone(normalize_month('Неизвестный 2026'))
        self.assertTrue(eligible('Октябрь 2026', date(2026, 10, 27)))
        self.assertFalse(eligible('Октябрь 2026', date(2026, 10, 26)))


    def test_both_source_and_ready_month_folders_are_created(self):
        class EmptyDisk:
            def __init__(self):
                self.folders = set()

            def mkdir(self, path):
                self.folders.add(path)

            def list(self, path):
                if path not in self.folders:
                    return None
                prefix = path.rstrip("/") + "/"
                return [{"name": p[len(prefix):], "type": "dir"}
                        for p in sorted(self.folders)
                        if p.startswith(prefix) and "/" not in p[len(prefix):]]

            def stat(self, path):
                return {"type": "dir"} if path in self.folders else None

        disk = EmptyDisk()
        project = {"slug": "atmosfera", "name": "Атмосфера", "folder": "Атмосфера",
                   "initial_units": ["Литер 1", "Литер 2"]}
        with tempfile.TemporaryDirectory() as tmp:
            run(disk, [project], date(2026, 10, 9), Path(tmp))
            for unit in project["initial_units"]:
                self.assertIn(disk_path("Атмосфера", "Исходные фотографии", unit, "Октябрь 2026"), disk.folders)
                self.assertIn(archive_path(project, unit, "2026-10"), disk.folders)
                self.assertIsNone(disk.stat(archive_path(project, unit, "2026-10") + "/_manifest.json"))
            self.assertEqual(__import__("json").loads((Path(tmp) / "atmosfera.json").read_text())["entries"], [])
            before = len(disk.folders)
            run(disk, [project], date(2026, 10, 9), Path(tmp))
            self.assertEqual(len(disk.folders), before)
            run(disk, [project], date(2026, 11, 2), Path(tmp))
            self.assertIn(archive_path(project, "Литер 1", "2026-11"), disk.folders)
            self.assertIn(disk_path("Атмосфера", "Исходные фотографии", "Литер 1", "Ноябрь 2026"), disk.folders)


    def test_finished_hierarchy_and_legacy_manifest_are_both_read(self):
        class MemoryDisk:
            def __init__(self):
                self.folders = set()
                self.files = {}
                self.uploads = 0

            def mkdir(self, path):
                self.folders.add(path)

            def stat(self, path):
                if path in self.files:
                    return {"type": "file"}
                if path in self.folders:
                    return {"type": "dir"}
                return None

            def list(self, path):
                if path not in self.folders:
                    return None
                prefix = path.rstrip("/") + "/"
                items = {}
                for p in self.folders:
                    if p.startswith(prefix) and "/" not in p[len(prefix):]:
                        items[p[len(prefix):]] = {"name": p[len(prefix):], "type": "dir"}
                for p in self.files:
                    if p.startswith(prefix) and "/" not in p[len(prefix):]:
                        items[p[len(prefix):]] = {"name": p[len(prefix):], "type": "file"}
                return list(items.values())

            def download(self, path):
                return self.files[path]

            def upload(self, path, data):
                self.uploads += 1
                self.files[path] = data

        project = {"slug": "atmosfera", "name": "Атмосфера", "folder": "Атмосфера",
                   "initial_units": ["Литер 1"]}
        disk = MemoryDisk()
        finished_root = disk_path("Атмосфера", "Готовые фотографии")
        disk.mkdir(finished_root)
        disk.mkdir(finished_root + "/Литер 1")
        old_sep = legacy_archive_path(project, "Литер 1", "2026-09")
        old_oct = legacy_archive_path(project, "Литер 1", "2026-10")
        new_oct = archive_path(project, "Литер 1", "2026-10")

        def mark(folder, month, filename):
            disk.mkdir(folder)
            disk.files[folder + "/" + filename] = b"sample-image"
            disk.files[folder + "/_manifest.json"] = json.dumps({
                "status": "complete", "project": "atmosfera", "unit": "Литер 1",
                "month": month, "photos": [{"site_file": filename, "source_name": "old.jpg"}]
            }).encode()

        mark(old_sep, "2026-09", "a" * 20 + "-site.jpg")
        mark(old_oct, "2026-10", "b" * 20 + "-site.jpg")
        mark(new_oct, "2026-10", "c" * 20 + "-site.jpg")
        with tempfile.TemporaryDirectory() as tmp:
            export_site(disk, [project], Path(tmp))
            rows = json.loads((Path(tmp) / "atmosfera.json").read_text())["entries"]
            self.assertEqual(len(rows), 2)
            self.assertEqual([x["month"] for x in rows], ["2026-10", "2026-09"])
            self.assertIn("c" * 20, rows[0]["photos"][0]["url"])
            self.assertIn("a" * 20, rows[1]["photos"][0]["url"])

        # A completed legacy archive also prevents repeat processing.
        source = disk_path("Атмосфера", "Исходные фотографии", "Литер 1")
        disk.mkdir(source)
        disk.mkdir(source + "/Октябрь 2026")
        disk.files[source + "/Октябрь 2026/_READY.txt"] = b""
        previous_uploads = disk.uploads
        process_unit(disk, project, "Литер 1", date(2026, 10, 29))
        self.assertEqual(disk.uploads, previous_uploads)

    def test_new_finished_path_is_nested(self):
        p = {"folder": "Атмосфера"}
        self.assertEqual(archive_path(p, "Литер 1", "2026-10"),
                         "app:/Атмосфера/Готовые фотографии/Литер 1/Октябрь 2026")
        self.assertEqual(legacy_archive_path(p, "Литер 1", "2026-10"),
                         "app:/Атмосфера/Готовые фотографии/Атмосфера. Литер 1. Октябрь 2026")

if __name__ == '__main__':
    unittest.main()
