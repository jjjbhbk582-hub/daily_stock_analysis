"""Offline synthetic contract tests; these are not market evidence."""
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

import verify_data as v


class ArchiveTests(unittest.TestCase):
    def test_mainboard_scope(self):
        for symbol in ['SH600000', 'sh601001', 'SH603001', 'SH605001', 'SZ000001', 'SZ001001', 'SZ002001', 'SZ003001']:
            self.assertTrue(v.is_mainboard(symbol))
        for symbol in ['SH000001', 'SH688001', 'SZ300001', 'BJ920001', '600000', 'SH60000X']:
            self.assertFalse(v.is_mainboard(symbol))

    def test_binary_offset_alignment(self):
        off, values = v.decode_feature(struct.pack('<4f', 2, 10, 11, 12), 5)
        self.assertEqual(off, 2)
        self.assertEqual(list(values), [10, 11, 12])

    def test_invalid_binary_offsets(self):
        for raw in [b'x', struct.pack('<2f', .5, 10), struct.pack('<2f', -1, 10), struct.pack('<2f', 5, 10), struct.pack('<2f', float('nan'), 10)]:
            with self.assertRaises(ValueError):
                v.decode_feature(raw, 5)

    def test_unsafe_names(self):
        for name in ['/root', '../x', 'qlib_bin/../x', 'qlib_bin//x', 'qlib_bin/a\\b', 'another/file']:
            with self.assertRaises(ValueError):
                v.safe_name(name)
        self.assertEqual(v.safe_name('qlib_bin/features/sh600000/close.day.bin'), 'qlib_bin/features/sh600000/close.day.bin')

    def test_calendar_rejects_duplicates_and_future(self):
        for dates in [b'2026-09-03\n2026-09-03\n', b'2026-09-04\n2026-09-07\n', b'2026-02-30\n']:
            with self.assertRaises(ValueError):
                v.read_calendar(dates, '2026-09-04')

    def test_digest_not_just_size(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'data'
            p.write_bytes(b'abc')
            v.verify_identity(p, 3, hashlib.sha256(b'abc').hexdigest())
            with self.assertRaises(ValueError):
                v.verify_identity(p, 3, hashlib.sha256(b'def').hexdigest())
            with self.assertRaises(ValueError):
                v.verify_identity(p, 4, hashlib.sha256(b'abc').hexdigest())

    def fixture(self, directory, partial=False, unsafe=False, bad_order=False):
        members = {'qlib_bin/calendars/day.txt': b'2015-01-05\n2015-01-06\n2015-01-07\n',
                   'qlib_bin/instruments/all.txt': b'SH600000\t2015-01-05\t2015-01-07\nSZ300001\t2015-01-05\t2015-01-07\n'}
        values = {'open': [10, 11, 12], 'close': [11, 12, 13], 'high': [12, 13, 14], 'low': [9, 10, 11], 'volume': [100, 200, 300], 'factor': [1, 1, 1]}
        if partial:
            values['open'][1] = float('nan')
        if bad_order:
            values['high'][1] = 1
        for field, data in values.items():
            members[f'qlib_bin/features/sh600000/{field}.day.bin'] = struct.pack('<4f', 0, *data)
        if unsafe:
            members['qlib_bin/../escape'] = b'bad'
        archive = Path(directory) / 'input.tar.gz'
        with tarfile.open(archive, 'w:gz') as t:
            for name, payload in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                t.addfile(info, io.BytesIO(payload))
        return archive

    def inspect(self, archive, start='2015-01-01'):
        return v.inspect_archive(archive, {'requested_start': start, 'requested_end': '2015-01-07'}, {'target_trade_date': '2015-01-07'})

    def test_full_pipeline_reads_actual_feature_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            summary, rows = self.inspect(self.fixture(d))
            self.assertEqual(summary['mainboard_symbols'], 1)
            self.assertEqual(summary['valid_mainboard_bars'], 3)
            self.assertEqual(rows[0]['first_valid_date'], '2015-01-05')
            self.assertEqual(rows[0]['last_valid_date'], '2015-01-07')
            self.assertIsNone(summary['official_historical_market_coverage'])
            self.assertFalse(summary['backtest_performed'])

    def test_partial_ohlc_is_reported_not_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            summary, rows = self.inspect(self.fixture(d, partial=True))
            self.assertEqual(rows[0]['partial_price_bars'], 1)
            self.assertEqual(summary['quality_flagged_symbols'], 1)

    def test_ohlc_order_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            summary, rows = self.inspect(self.fixture(d, bad_order=True))
            self.assertEqual(rows[0]['invalid_price_bars'], 1)
            self.assertEqual(summary['quality_flagged_symbols'], 1)

    def test_unsafe_archive_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                self.inspect(self.fixture(d, unsafe=True))
            self.assertFalse((Path(d) / 'escape').exists())

    def test_empty_requested_range_not_a_success(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                self.inspect(self.fixture(d), '2016-01-01')

    def test_target_date_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                v.inspect_archive(self.fixture(d), {'requested_start': '2015-01-01', 'requested_end': '2015-01-07'}, {'target_trade_date': '2015-01-06'})


if __name__ == '__main__':
    unittest.main()
