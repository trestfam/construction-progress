import unittest
from datetime import date
from scripts.progress import eligible, month_limit, label_month, disk_path, normalize_month

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

if __name__ == '__main__':
    unittest.main()
