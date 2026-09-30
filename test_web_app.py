import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import web_app as web


class WebTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_home_and_invalid_upload(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        with patch.dict('os.environ', {'GOOGLE_API_KEY': 'test'}):
            response = self.client.post('/api/jobs', data={'file': (io.BytesIO(b'bad'), 'bad.txt')})
            self.assertEqual(response.status_code, 400)
            response = self.client.post('/api/jobs', data={'file': (io.BytesIO(b'bad'), 'bad.xlsx')})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(web.LOCK.locked())

    def test_upload_job_zip_and_preview(self):
        import pandas as pd
        workbook = io.BytesIO()
        pd.DataFrame({"Restaurant Name": ["Example Cafe"], "City": ["Sample City"],
                      "Area": ["Market Road"]}).to_excel(workbook, index=False)
        with tempfile.TemporaryDirectory() as folder, patch.object(web, 'JOBS', Path(folder)), patch.dict('os.environ', {'GOOGLE_API_KEY': 'test'}):
            with patch('threading.Thread.start') as start:
                response = self.client.post('/api/jobs', data={
                    'file': (io.BytesIO(workbook.getvalue()), 'restaurants.xlsx'),
                    'format': 'wide',
                })
                self.assertEqual(response.status_code, 202)
                start.assert_called_once()
            job_id = response.json['id']
            root = Path(folder) / job_id
            def fake_worker(*args, **kwargs):
                from PIL import Image
                target = root / 'Enhanced_Restaurant_Images_16x9' / 'Example'
                target.mkdir(parents=True)
                Image.new('RGB', (16, 9), 'green').save(target / '1_food.jpg')
                (root / 'output').mkdir()
                return SimpleNamespace(returncode=0)
            with patch.object(web.subprocess, 'run', side_effect=fake_worker):
                web.process_job(root, True)
            status = self.client.get(f'/api/jobs/{job_id}').json
            self.assertEqual(status['state'], 'complete')
            self.assertEqual(status['count'], 1)
            response = self.client.get(f'/api/jobs/{job_id}/download')
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertEqual(archive.namelist(), ['Images/Example/1_food.jpg'])
            response.close()
            preview = self.client.get(f'/api/jobs/{job_id}/image/' + status['images'][0])
            self.assertEqual(preview.status_code, 200)
            preview.close()
            self.assertEqual(self.client.get(f'/api/jobs/{job_id}/image/input.xlsx').status_code, 404)

    def test_cross_origin_upload_blocked(self):
        self.assertEqual(self.client.post('/api/jobs', headers={'Origin': 'https://example.com'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
