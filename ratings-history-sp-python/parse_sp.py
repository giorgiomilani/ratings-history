#!/usr/bin/env python3
"""Flatten S&P SEC rating-history XML from a local ZIP, without preprocessing."""
import argparse
import csv
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

TAG_TO_COLUMN = dict(zip(
    'RAN FCD SSC ISSNAME LEI OBT INSTNAME CUSIP CR MD PV IP R RAD RAC RT RST RTT OAN WST ROL ISI ISIS INI INIS CIK OI OIS OIOS OSC OIG OBNAME'.split(),
    'rating_agency_name file_creating_date sec_category issuer_name legal_entity_identifier object_type_rated instrument_name CUSIP_number coupon_date maturity_date par_value issued_paid rating rating_action_date rating_action_class rating_type rating_sub_type rating_type_term other_announcement_type watch_status rating_outlook issuer_identifier issuer_identifier_schema instrument_identifier instrument_identifier_schema central_index_key obligor_identifier obligor_identifier_schema obligor_identifier_other obligor_sec_category obligor_industry_group obligor_name'.split()
))
COLUMNS = list(TAG_TO_COLUMN.values())
SCOPES = {'ROCRA', 'OD', 'ISD', 'IND', 'ORD', 'INRD'}
RECORDS = {'ORD', 'INRD'}
NS_PREFIX = 'http://xbrl.sec.gov/ratings/'
NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'


def rating_tag(tag):
    if tag.startswith('{'):
        namespace, name = tag[1:].split('}', 1)
        if namespace.startswith(NS_PREFIX):
            return name
    return None


def iter_records(source):
    """Read each record once; parent metadata is scoped, never sibling-filled."""
    frames = []
    elements = []
    for event, element in ET.iterparse(source, events=('start', 'end')):
        tag = rating_tag(element.tag)
        if event == 'start':
            elements.append(element)
            if tag in SCOPES:
                frames.append((tag, {}))
            continue
        if tag in TAG_TO_COLUMN:
            if not frames:
                raise ValueError(f'Field {tag} outside rating disclosure')
            if len(element):
                raise ValueError(f'Unexpected nested content in field {tag}')
            values = frames[-1][1]
            if tag in values:
                raise ValueError(f'Repeated field {tag} in {frames[-1][0]}')
            values[tag] = (None if element.get(NIL) in ('true', '1')
                           else element.text if element.text is not None else '')
        elif tag and tag not in SCOPES:
            raise ValueError(f'Unmapped rating XML element: {tag}')
        if tag in RECORDS:
            expected = 'OD' if tag == 'ORD' else 'IND'
            if len(frames) < 2 or frames[-2][0] != expected:
                raise ValueError(f'{tag} outside expected {expected} parent')
            merged = {}
            for _, values in frames:
                merged.update(values)
            row = {column: merged.get(key) for key, column in TAG_TO_COLUMN.items()}
            yield tag, row
        if tag in SCOPES:
            frames.pop()
        elements.pop()
        if elements:
            elements[-1].remove(element)
        element.clear()


class Output:
    def __init__(self, directory, output_format, batch_size):
        self.directory = directory
        self.output_format = output_format
        self.batch_size = batch_size
        self.files = {}
        self.pa = self.pq = self.schema = None
        if output_format in ('parquet', 'both'):
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise RuntimeError('Parquet requires: python -m pip install pyarrow') from exc
            self.pa, self.pq = pa, pq
            self.schema = pa.schema([(column, pa.string()) for column in COLUMNS])

    def append(self, row):
        date = row['file_creating_date']
        agency = row['rating_agency_name']
        category = row['sec_category'] or row['obligor_sec_category']
        if not date or not agency or not category:
            raise ValueError('Missing file date, agency, or category for output filename')
        name = f"{date.replace('-', '')} {agency} {category}"
        if any(c in name for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in name):
            raise ValueError(f'Unsafe output filename: {name!r}')
        if name not in self.files:
            entry = {'rows': 0, 'batch': [], 'csv_handle': None, 'writer': None, 'parquet': None}
            self.files[name] = entry
            if self.output_format in ('csv', 'both'):
                entry['csv_handle'] = (self.directory / (name + '.csv')).open('w', encoding='utf-8', newline='')
                entry['writer'] = csv.DictWriter(entry['csv_handle'], fieldnames=COLUMNS)
                entry['writer'].writeheader()
            if self.pq:
                entry['parquet'] = self.pq.ParquetWriter(self.directory / (name + '.parquet'), self.schema, compression='snappy')
        entry = self.files[name]
        if entry['writer']:
            entry['writer'].writerow(row)
        if entry['parquet']:
            entry['batch'].append(row)
            if len(entry['batch']) >= self.batch_size:
                self.flush(entry)
        entry['rows'] += 1

    def flush(self, entry):
        if entry['batch']:
            table = self.pa.Table.from_pylist(entry['batch'], schema=self.schema)
            entry['parquet'].write_table(table)
            entry['batch'].clear()

    def close(self):
        for entry in self.files.values():
            try:
                if entry['parquet']:
                    self.flush(entry)
            finally:
                if entry['parquet']:
                    entry['parquet'].close()
                if entry['csv_handle']:
                    entry['csv_handle'].close()


def convert(archive, output_dir, output_format='csv', batch_size=25000, overwrite=False):
    archive, output_dir = Path(archive), Path(output_dir)
    if batch_size < 1:
        raise ValueError('batch-size must be positive')
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    with tempfile.TemporaryDirectory(prefix='.sp-parsing-', dir=output_dir) as temporary:
        staging = Path(temporary)
        output = Output(staging, output_format, batch_size)
        try:
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    if member.is_dir() or not member.filename.lower().endswith('.xml'):
                        continue
                    try:
                        with zf.open(member) as source:
                            for kind, row in iter_records(source):
                                output.append(row)
                                counts[kind] += 1
                    except Exception as exc:
                        raise ValueError(f'{member.filename}: {exc}') from exc
                    counts['xml_files'] += 1
                    if counts['xml_files'] % 1000 == 0:
                        print(f"Parsed {counts['xml_files']:,} XML files; {counts['ORD'] + counts['INRD']:,} rows", file=sys.stderr)
            if not counts['xml_files'] or not output.files:
                raise ValueError('Archive contains no XML rating records')
        finally:
            output.close()
        summary = {
            'archive': archive.name,
            'xml_files': counts['xml_files'],
            'obligor_records': counts['ORD'],
            'instrument_records': counts['INRD'],
            'total_records': counts['ORD'] + counts['INRD'],
            'format': output_format,
            'outputs': {name: item['rows'] for name, item in output.files.items()},
            'columns': COLUMNS,
        }
        (staging / 'parse_summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        pending = list(staging.iterdir())
        for file in pending:
            destination = output_dir / file.name
            if destination.exists() and not overwrite:
                raise FileExistsError(f'{destination} already exists; use --overwrite to replace')
        for file in pending:
            os.replace(file, output_dir / file.name)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path', type=Path, help='Already-downloaded S&P ZIP')
    parser.add_argument('--output-dir', type=Path, default=Path('sp-output'))
    parser.add_argument('--format', choices=('csv', 'parquet', 'both'), default='csv')
    parser.add_argument('--batch-size', type=int, default=25000)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        result = convert(args.zip_path, args.output_dir, args.format, args.batch_size, args.overwrite)
    except Exception as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
