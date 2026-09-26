import unittest
from crawler import detect


class DetectionTest(unittest.TestCase):
    def test_signatures(self):
        self.assertEqual(detect('test.kicad_pcb', b'(kicad_pcb (version 1))'), 'KiCad')
        self.assertIsNone(detect('test.kicad_pcb', b'garbage'))
        self.assertEqual(detect('test.brd', b'<?xml version="1.0"?><eagle version="9">'), 'Eagle')
        self.assertIsNone(detect('test.brd', b'random'))
        self.assertEqual(detect('test.PcbDoc', bytes.fromhex('d0cf11e0a1b11ae1') + b'payload'), 'Altium')


if __name__ == '__main__':
    unittest.main()
