import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from report_utils import save_excel_report


class ReportTests(unittest.TestCase):
    def test_locked_report_preserved_and_alternate_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "report.xlsx"
            destination.write_bytes(b"existing report")
            with patch.object(Path, "replace", side_effect=PermissionError("File is open")):
                saved = save_excel_report(pd.DataFrame({"Status": ["SUCCESS"]}), destination)
            self.assertNotEqual(saved, destination)
            self.assertEqual(destination.read_bytes(), b"existing report")
            self.assertEqual(pd.read_excel(saved).iloc[0]["Status"], "SUCCESS")

    def test_normal_save_replaces_report(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "report.xlsx"
            saved = save_excel_report(pd.DataFrame({"Count": [75]}), destination)
            self.assertEqual(saved, destination)
            self.assertEqual(pd.read_excel(saved).iloc[0]["Count"], 75)
            self.assertEqual(len(list(Path(folder).glob("*.xlsx"))), 1)
