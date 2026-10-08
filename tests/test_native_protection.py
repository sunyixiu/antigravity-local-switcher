from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_switcher as core


class NativeProtectionTests(unittest.TestCase):
    def test_dpapi_round_trip_and_tamper_rejection(self):
        protector = core.Protector()
        try:
            encrypted = protector.transform(b'synthetic-dpapi-data', True)
        except core.LocalError:
            self.skipTest('Windows DPAPI unavailable in the current agent logon context')
        self.assertNotIn(b'synthetic-dpapi-data', encrypted)
        self.assertEqual(protector.transform(encrypted, False), b'synthetic-dpapi-data')
        corrupted = bytearray(encrypted)
        corrupted[-1] ^= 1
        with self.assertRaises(core.LocalError):
            protector.transform(bytes(corrupted), False)


if __name__ == '__main__':
    unittest.main()
