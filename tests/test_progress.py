import unittest
import tempfile
from pathlib import Path
from datetime import date
from scripts.progress import eligible, month_limit, label_month, disk_path, normalize_month, archive_path, run

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

if __name__ == '__main__':
    unittest.main()
