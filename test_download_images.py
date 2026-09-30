import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import download_images as app


class DownloaderTests(unittest.TestCase):
    def test_wrong_brand_and_wrong_locality_are_rejected(self):
        restaurant = dict(name="McDonald's", area="Panchvati", city="Ahmedabad", address="")
        for name, address in [("Burger King", "Panchvati, Ahmedabad"),
                              ("McDonald's", "Ellisbridge, Ahmedabad"),
                              ("McDonald's", "Panchvati, Mumbai")]:
            best = app.choose_best_place(restaurant, [{"id": "wrong", "displayName": {"text": name}, "formattedAddress": address}])
            self.assertTrue(best["blocked"])
        best = app.choose_best_place(restaurant, [{"id": "right", "displayName": {"text": "McDonalds"}, "formattedAddress": "Panchvati, Ahmedabad"}])
        self.assertFalse(best["blocked"])

    def test_same_brand_ambiguous_branches_blocked(self):
        restaurant = dict(name="McDonald's", area="Panchvati", city="Ahmedabad", address="")
        places = [{"id": str(i), "displayName": {"text": "McDonald's"}, "formattedAddress": "Panchvati, Ahmedabad"} for i in range(2)]
        self.assertTrue(app.choose_best_place(restaurant, places)["blocked"])

    def test_cross_place_photo_resource_is_rejected(self):
        restaurant = dict(name="Test Cafe", address="12 Market Road", city="Goa", area="Market Road")
        client = Mock()
        client.search_places.return_value = [{"id": "correct", "displayName": {"text": "Test Cafe"},
            "formattedAddress": "12 Market Road, Goa", "photos": [{"name": "places/wrong/photos/1"}]}]
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "OUTPUT_FOLDER", folder):
            result = app.process_restaurant(1, 2, restaurant, "Test Cafe", client)
        client.download_photo.assert_not_called()
        self.assertEqual(result["status"], "DOWNLOAD_ERROR")

    def test_missing_seating_falls_back_to_food(self):
        from select_photos import choose_photos
        candidates = [
            {"category": "food", "score": .99},
            {"category": "food", "score": .98},
            {"category": "ambience", "score": .9},
            {"category": "uncertain", "score": .6},
        ]
        chosen = choose_photos(candidates)
        self.assertEqual([slot for slot, _ in chosen], [1, 2, 3])
        self.assertEqual(chosen[1][1]["score"], .99)

    def test_no_seating_selects_only_food(self):
        from select_photos import choose_photos
        candidates = [{"category": "food", "score": score} for score in (.99, .95, .90, .85)]
        candidates.append({"category": "other", "score": .99})
        chosen = choose_photos(candidates)
        self.assertEqual(len(chosen), 3)
        self.assertTrue(all(item["category"] == "food" for _, item in chosen))

    def test_insufficient_food_leaves_slots_empty(self):
        from select_photos import choose_photos
        self.assertEqual(len(choose_photos([{"category": "food", "score": .99}])), 1)

    def test_address_only_match_and_missing_location(self):
        restaurant = {"name": "Test Cafe", "address": "12 Market Road, Goa"}
        scores = app.calculate_match_score(restaurant, "Test Cafe", restaurant["address"])
        self.assertEqual(app.classify_match(scores[0], scores[1], scores[3]), "HIGH")
        scores = app.calculate_match_score({"name": "Test Cafe"}, "Test Cafe", "Goa")
        self.assertEqual(app.classify_match(scores[0], scores[1], scores[3]), "LOW_CONFIDENCE")

    def test_partial_download_is_retryable(self):
        restaurant = dict(name="Test Cafe", address="12 Market Road", city="Goa", area="")
        client = Mock()
        client.search_places.return_value = [{
            "id": "test", "displayName": {"text": "Test Cafe"},
            "formattedAddress": "12 Market Road, Goa",
            "photos": [{"name": "places/test/photos/1"}, {"name": "places/test/photos/2"}],
        }]
        client.download_photo.side_effect = [None, RuntimeError("download failed")]
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "OUTPUT_FOLDER", folder):
            result = app.process_restaurant(1, 2, restaurant, "Test Cafe", client)
            self.assertEqual(result["status"], "DOWNLOAD_ERROR")
            self.assertEqual(result["number_of_images"], 1)
            self.assertIn("download failed", result["error"])
            progress = app.ProgressStore(str(Path(folder) / "progress.json"))
            progress.update("2", result)
            with patch.object(app, "REPORT_FILE", str(Path(folder) / "report.xlsx")), patch.object(app, "FAILED_FILE", str(Path(folder) / "failed.xlsx")):
                app.write_reports(progress)
                failed = app.pd.read_excel(app.FAILED_FILE)
                self.assertEqual(failed.iloc[0]["Status"], "DOWNLOAD_ERROR")


if __name__ == "__main__":
    unittest.main()
