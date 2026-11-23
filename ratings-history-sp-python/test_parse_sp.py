import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from parse_sp import iter_records, convert


def xml(body):
    return ('<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance" '
            'xmlns:r="http://xbrl.sec.gov/ratings/2015-03-31"><r:ROCRA>'
            '<r:RAN>S&amp;P</r:RAN><r:FCD>2026-11-01</r:FCD>' + body + '</r:ROCRA></x:xbrl>').encode()


class ParsingTests(unittest.TestCase):
    def test_action_fields_are_not_inherited_and_duplicates_survive(self):
        body = ('<r:OD><r:OSC>Corporate</r:OSC><r:OBNAME> A &amp; B </r:OBNAME>'
                '<r:ORD><r:R>AA</r:R><r:RAC>NW</r:RAC><r:ROL>Stable</r:ROL></r:ORD>'
                '<r:ORD><r:R>A</r:R><r:ROL/></r:ORD>'
                '<r:ORD><r:R>A</r:R><r:ROL/></r:ORD></r:OD>')
        rows = [r for _, r in iter_records(io.BytesIO(xml(body)))]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1], rows[2])
        self.assertEqual(rows[0]['obligor_name'], ' A & B ')
        self.assertIsNone(rows[1]['rating_action_class'])
        self.assertEqual(rows[1]['rating_outlook'], '')

    def test_instrument_and_entity_boundaries(self):
        body = ('<r:ISD><r:SSC>Corporate</r:SSC><r:ISSNAME>First</r:ISSNAME>'
                '<r:IND><r:CUSIP>000001</r:CUSIP><r:INRD><r:R>A</r:R></r:INRD></r:IND>'
                '<r:IND><r:INI>X</r:INI><r:INRD><r:R>B</r:R></r:INRD></r:IND></r:ISD>'
                '<r:ISD><r:SSC>Corporate</r:SSC><r:ISSNAME>Second</r:ISSNAME>'
                '<r:IND><r:INRD><r:R>C</r:R></r:INRD></r:IND></r:ISD>')
        rows = [r for _, r in iter_records(io.BytesIO(xml(body)))]
        self.assertEqual(rows[0]['CUSIP_number'], '000001')
        self.assertIsNone(rows[1]['CUSIP_number'])
        self.assertIsNone(rows[2]['instrument_identifier'])
        self.assertEqual(rows[2]['issuer_name'], 'Second')

    def test_unknown_fields_fail_instead_of_disappearing(self):
        with self.assertRaisesRegex(ValueError, 'Unmapped'):
            list(iter_records(io.BytesIO(xml('<r:NEW>value</r:NEW>'))))

    def test_malformed_archive_does_not_publish_partial_csv(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            archive = td / 'source.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('good.xml', xml('<r:OD><r:OSC>Corporate</r:OSC><r:ORD><r:R>A</r:R></r:ORD></r:OD>'))
                z.writestr('bad.xml', '<broken>')
            with self.assertRaises(ValueError):
                convert(archive, td / 'out')
            self.assertEqual(list((td / 'out').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
