import unittest

from src.evaluation.phase20_protocol import WORKBOOK_SHEETS


class ExcelSheetsTests(unittest.TestCase):
    def test_requested_workbook_tabs_are_present_and_excel_safe(self):
        self.assertEqual(len(WORKBOOK_SHEETS), 21)
        self.assertEqual(len(set(WORKBOOK_SHEETS)), len(WORKBOOK_SHEETS))
        self.assertTrue(all(len(name) <= 31 for name in WORKBOOK_SHEETS))
        self.assertEqual(WORKBOOK_SHEETS[-1], "20_Final_System")


if __name__ == "__main__":
    unittest.main()
