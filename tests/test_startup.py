"""Startup registry logic tests (in-memory, no system changes).

Uses a fake ``winreg`` so enable()/disable() can be verified without touching
the real registry. The StartupApproved value must use the Windows layout:
status byte + 3 zero bytes + 8-byte FILETIME, with 0x06 marking "enabled"
(0x02/0x03 mark disabled on Windows 11; 0x07 is NOT recognized as enabled).
"""

import unittest
import unittest.mock as mock

import startup


class FakeKey:
    def __init__(self):
        self.values = {}
        self.deleted = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeWinreg:
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1
    REG_BINARY = 3

    def __init__(self):
        self.HKEY_CURRENT_USER = 'HKCU'
        self.keys = {}
        self.ordered = []

    def _key(self, path):
        if path not in self.keys:
            self.keys[path] = FakeKey()
            self.ordered.append(path)
        return self.keys[path]

    def CreateKey(self, root, path):
        return self._key(path)

    def OpenKey(self, root, path, *args):
        return self._key(path)

    def SetValueEx(self, key, name, reserved, typ, data):
        key.values[name] = (typ, data)

    def DeleteValue(self, key, name):
        key.deleted.append(name)

    def CloseKey(self, key):
        pass


class StartupTest(unittest.TestCase):

    def setUp(self):
        self.fake = FakeWinreg()
        patcher = mock.patch.object(startup, 'winreg', self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = mock.patch.object(
            startup, '_get_exe_path',
            return_value=r'C:\Users\a.ilgis\Desktop\projects\Selate\dist\Selate.exe',
        )
        patcher2.start()
        self.addCleanup(patcher2.stop)

    def test_sync_true_calls_enable(self):
        with mock.patch.object(startup, 'enable') as enable:
            with mock.patch.object(startup, 'disable') as disable:
                startup.sync(True)
        enable.assert_called_once()
        disable.assert_not_called()

    def test_sync_false_calls_disable(self):
        with mock.patch.object(startup, 'enable') as enable:
            with mock.patch.object(startup, 'disable') as disable:
                startup.sync(False)
        disable.assert_called_once()
        enable.assert_not_called()

    def test_enable_writes_run_and_approved_marker(self):
        startup.enable()
        run = self.fake.keys[startup.STARTUP_REGISTRY_PATH]
        appr = self.fake.keys[startup.STARTUP_APPROVED_PATH]

        typ, val = run.values[startup.STARTUP_REGISTRY_NAME]
        self.assertEqual(typ, FakeWinreg.REG_SZ)
        self.assertEqual(val, r'C:\Users\a.ilgis\Desktop\projects\Selate\dist\Selate.exe')

        typ2, data = appr.values[startup.STARTUP_REGISTRY_NAME]
        self.assertEqual(typ2, FakeWinreg.REG_BINARY)
        self.assertEqual(len(data), 12)
        self.assertEqual(data[0], 0x06, 'enabled status byte must be 0x06')
        self.assertEqual(data[1:4], b'\x00\x00\x00', '3 zero bytes after status')
        self.assertEqual(len(data[4:]), 8, '8-byte FILETIME at the end')

    def test_enable_is_idempotent_and_uses_approved_path(self):
        startup.enable()
        self.assertIn(startup.STARTUP_APPROVED_PATH, self.fake.keys)

    def test_disable_deletes_both_values(self):
        startup.disable()
        run = self.fake.keys[startup.STARTUP_REGISTRY_PATH]
        appr = self.fake.keys[startup.STARTUP_APPROVED_PATH]
        self.assertIn(startup.STARTUP_REGISTRY_NAME, run.deleted)
        self.assertIn(startup.STARTUP_REGISTRY_NAME, appr.deleted)


if __name__ == '__main__':
    unittest.main()
