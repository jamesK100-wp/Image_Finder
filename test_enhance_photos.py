import tempfile
import unittest
from pathlib import Path
from PIL import Image
from enhance_photos import enhance_image


class EnhancementTests(unittest.TestCase):
    def test_wide_export_preserves_portrait_and_adds_padding(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "portrait.jpg"
            destination = Path(folder) / "wide.jpg"
            Image.new("RGB", (600, 900), "white").save(source)
            original_bytes = source.read_bytes()
            enhance_image(source, destination, wide=True)
            self.assertEqual(source.read_bytes(), original_bytes)
            with Image.open(destination) as saved:
                self.assertEqual(saved.size, (2560, 1440))
                self.assertLess(max(saved.getpixel((0, 720))), 30)
                self.assertGreater(min(saved.getpixel((1280, 720))), 240)

    def test_original_preserved_and_upscale_capped(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "original.jpg"
            destination = Path(folder) / "enhanced.jpg"
            Image.new("RGB", (100, 50), "tan").save(source)
            original_bytes = source.read_bytes()
            result = enhance_image(source, destination)
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(result["enhanced_size"], (200, 100))
            with Image.open(destination) as saved:
                self.assertEqual(saved.format, "JPEG")
                self.assertEqual(saved.size, (200, 100))
            with self.assertRaises(ValueError):
                enhance_image(source, source)

    def test_orientation_corrected_and_original_size_option(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "original.jpg"
            destination = Path(folder) / "enhanced.jpg"
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGB", (100, 50), "tan").save(source, exif=exif)
            result = enhance_image(source, destination, long_edge=0)
            self.assertEqual(result["enhanced_size"], (50, 100))


if __name__ == "__main__":
    unittest.main()
