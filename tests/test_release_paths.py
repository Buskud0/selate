import importlib
import os
import unittest
from unittest.mock import patch


class ReleasePathsTests(unittest.TestCase):
    def test_data_dir_uses_localappdata_when_available(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': r'C:\Temp\LocalAppData', 'APPDATA': r'C:\Temp\AppData'}, clear=False):
            config = importlib.reload(__import__('config'))
            self.assertEqual(config.get_data_dir(), r'C:\Temp\LocalAppData\Selate')


if __name__ == '__main__':
    unittest.main()
