"""Excel text remains literal and valid XML without changing valid text."""
import unittest
from io import BytesIO
from openpyxl import Workbook, load_workbook
from inspection_plan_excel import write_text

class ExcelTextTests(unittest.TestCase):
    def test_all_forbidden_xml_characters_roundtrip_as_visible_codes(self):
        codes=[*range(9),11,12,*range(14,32),0xD800,0xDFFF,0xFFFE,0xFFFF]
        wb=Workbook();ws=wb.active
        for row,code in enumerate(codes,1):
            write_text(ws.cell(row,1),'前'+chr(code)+'後')
        output=BytesIO();wb.save(output);output.seek(0)
        saved=load_workbook(output).active
        for row,code in enumerate(codes,1):
            self.assertEqual(saved.cell(row,1).value,f'前[U+{code:04X}]後')
            self.assertEqual(saved.cell(row,1).data_type,'s')

    def test_valid_unicode_whitespace_and_formula_text_are_unchanged(self):
        values=['日本語😀𠮷', '改行\n次行\t項目\r復帰', '=SUM(1,2)', '+1', '-1', '@name', 'literal[U+000B]']
        wb=Workbook();ws=wb.active
        for row,value in enumerate(values,1):
            write_text(ws.cell(row,1),value)
            self.assertEqual(ws.cell(row,1).value,value)
            # Compare to the previous literal-text path: the XML writer may
            # normalize carriage return independently of our sanitizer.
            ws.cell(row,2).value=value;ws.cell(row,2).data_type='s'
        output=BytesIO();wb.save(output);output.seek(0)
        saved=load_workbook(output).active
        for row,value in enumerate(values,1):
            self.assertEqual(saved.cell(row,1).value,saved.cell(row,2).value)
            self.assertEqual(saved.cell(row,1).data_type,'s')
