import unittest
from cad_crawler import classify, FORMATS, AMBIGUOUS


class FormatsTest(unittest.TestCase):
    def test_requested_extensions(self):
        extensions = '''stl stp step glb igs iges x_t x_b dwg dxf bak
          sldprt sldasm ipt iam aim catpart catproduct cgr prt asm rvt rfa pln 3dm f3d f3z'''.split()
        self.assertTrue(all('.' + x in FORMATS or '.' + x in AMBIGUOUS for x in extensions))

    def test_magic_and_ambiguity(self):
        self.assertEqual(classify('board.GLB', b'glTF' + b'\x00' * 30), ('glTF GLB', 'header_verified'))
        self.assertIsNone(classify('board.glb', b'not a glb'))
        self.assertIsNone(classify('backup.bak', b'editor backup'))
        self.assertEqual(classify('backup.bak', b'AC1032'), ('AutoCAD DWG backup', 'header_verified'))
        self.assertEqual(classify('shape.prt', b'\x00binary'), ('Creo or Siemens NX part/assembly', 'ambiguous_extension'))
        self.assertIsNone(classify('source.asm', b'hello world\n'))
        self.assertEqual(classify('part.f3d', b'archive content'), ('Fusion 360 design', 'extension_only'))
        self.assertEqual(classify('part.f3z', b'PK\x03\x04data'), ('Fusion 360 assembly', 'header_verified'))
        self.assertEqual(classify('part.3dm', b'3D Geometry File Format 80'), ('Rhino 3DM', 'header_verified'))


if __name__ == '__main__':
    unittest.main()
