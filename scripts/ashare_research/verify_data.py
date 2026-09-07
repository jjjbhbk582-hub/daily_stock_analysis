"""Read-only, standard-library Qlib archive acquisition and coverage probe.

No app imports, API keys, brokerage calls, strategy signals, or return estimates.
Synthetic tests exercise structure; the actual archive is downloaded separately.
"""
from __future__ import annotations

import argparse
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import time
from urllib.request import Request, urlopen

FIELDS = ('open', 'high', 'low', 'close', 'volume', 'factor')
PRICES = FIELDS[:4]
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 10 * 1024**3
MAINBOARD = re.compile(r'(?:SH(?:600|601|603|605)|SZ(?:000|001|002|003))\d{3}\Z')
FEATURE = re.compile(r'qlib_bin/features/([a-zA-Z]{2}\d{6})/([a-z_]+)\.day\.bin\Z')


def is_mainboard(symbol: str) -> bool:
    return bool(MAINBOARD.fullmatch(symbol.upper()))


def safe_name(name: str) -> str:
    trimmed = name.rstrip('/')
    parts = trimmed.split('/')
    if ('\\' in name or not trimmed or trimmed.startswith('/')
            or any(p in ('', '.', '..') for p in parts)
            or parts[0] != 'qlib_bin' or str(PurePosixPath(trimmed)) != trimmed):
        raise ValueError(f'Unsafe archive member: {name!r}')
    return trimmed


def decode_feature(raw: bytes, calendar_length: int) -> tuple[int, array]:
    if len(raw) < 8 or len(raw) % 4:
        raise ValueError('Feature must contain a float32 offset and values')
    values = array('f')
    values.frombytes(raw)
    if sys.byteorder != 'little':
        values.byteswap()
    offset = values.pop(0)
    if not math.isfinite(offset) or offset < 0 or offset != int(offset):
        raise ValueError('Invalid Qlib calendar offset')
    if int(offset) + len(values) > calendar_length:
        raise ValueError('Feature extends beyond the actual trading calendar')
    return int(offset), values


def read_calendar(raw: bytes, requested_end: str) -> list[str]:
    days = raw.decode('utf-8').splitlines()
    if not days or days != sorted(set(days)):
        raise ValueError('Calendar is empty, unsorted or duplicated')
    for day in days:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('Noncanonical calendar date')
    if days[-1] > requested_end:
        raise ValueError('Actual calendar extends after fixed research cutoff')
    return days


def verify_identity(path: Path, size: int, sha256: str) -> None:
    if path.stat().st_size != size:
        raise ValueError(f'Byte count mismatch for {path.name}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != sha256.removeprefix('sha256:'):
        raise ValueError(f'SHA-256 mismatch for {path.name}')


def download(url: str, path: Path, size: int, sha256: str) -> None:
    if not url.startswith('https://github.com/chenditc/investment_data/releases/download/'):
        raise ValueError('Only the configured public release source is allowed')
    partial = path.with_suffix(path.suffix + '.partial')
    last_error = None
    for attempt in range(2):
        received = 0
        started = time.monotonic()
        try:
            request = Request(url, headers={'User-Agent': 'ashare-readonly-data-validation/1.0'})
            with urlopen(request, timeout=45) as response, partial.open('wb') as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    received += len(block)
                    if received > size or time.monotonic() - started > 420:
                        raise ValueError('Download exceeds fixed byte/time budget')
                    output.write(block)
            verify_identity(partial, size, sha256)
            partial.replace(path)
            print(f'Download verified: {path.name}, {received} bytes', flush=True)
            return
        except Exception as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            print(f'Download attempt {attempt + 1} failed: {type(exc).__name__}: {exc}', flush=True)
    raise RuntimeError(f'Download failed: {path.name}: {last_error}')


def inspect_archive(archive: Path, config: dict, manifest: dict) -> tuple[dict, list[dict]]:
    calendar_raw = None
    instruments_raw = None
    feature_bytes: dict[str, dict[str, bytes]] = {}
    seen = set()
    expanded = 0
    # No extract/extractall: never create files using names supplied by the archive.
    with tarfile.open(archive, mode='r|gz') as source:
        for member in source:
            name = safe_name(member.name)
            if name in seen or len(seen) >= 200000:
                raise ValueError('Duplicate or excessive archive members')
            seen.add(name)
            if not (member.isfile() or member.isdir()) or getattr(member, 'sparse', None):
                raise ValueError(f'Unsupported archive member type: {name}')
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise ValueError('Member exceeds the memory budget')
            expanded += member.size
            if expanded > MAX_EXPANDED_BYTES:
                raise ValueError('Archive exceeds expanded-byte budget')
            match = FEATURE.fullmatch(name)
            wanted = match and is_mainboard(match[1]) and match[2] in FIELDS
            if name not in ('qlib_bin/calendars/day.txt', 'qlib_bin/instruments/all.txt') and not wanted:
                continue
            if not member.isfile():
                raise ValueError('Expected a regular data file')
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError('Missing member stream')
            raw = stream.read()
            if len(raw) != member.size:
                raise ValueError('Truncated member')
            if name == 'qlib_bin/calendars/day.txt':
                calendar_raw = raw
            elif name == 'qlib_bin/instruments/all.txt':
                instruments_raw = raw
            else:
                feature_bytes.setdefault(match[1].upper(), {})[match[2]] = raw
    if calendar_raw is None or instruments_raw is None:
        raise ValueError('Missing actual calendar or instrument list')
    days = read_calendar(calendar_raw, config['requested_end'])
    if days[-1] != manifest['target_trade_date']:
        raise ValueError('Actual calendar and manifest target disagree')
    left = bisect_left(days, config['requested_start'])
    right = bisect_right(days, config['requested_end'])
    if left >= right:
        raise ValueError('No actual calendar dates in requested period')
    instruments: dict[str, list[tuple[str, str]]] = {}
    for line in instruments_raw.decode('utf-8').splitlines():
        columns = line.split('\t')
        if len(columns) != 3:
            raise ValueError('Invalid instrument list row')
        symbol, start, end = columns
        if not re.fullmatch(r'[A-Z]{2}\d{6}', symbol):
            raise ValueError('Unexpected security code in instrument list')
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError('Reversed instrument interval')
        if end > days[-1]:
            raise ValueError('Instrument interval extends beyond actual calendar')
        intervals = instruments.setdefault(symbol, [])
        if (start, end) in intervals:
            raise ValueError('Duplicate instrument interval')
        intervals.append((start, end))
    mainboard = sorted(s for s in instruments if is_mainboard(s))
    if not mainboard:
        raise ValueError('No mainboard security codes in input')
    rows = []
    yearly = Counter()
    daily = Counter()
    for number, symbol in enumerate(mainboard, 1):
        binaries = feature_bytes.pop(symbol, {})
        series = {}
        errors = []
        for field in FIELDS:
            if field not in binaries:
                errors.append(f'missing:{field}')
                continue
            try:
                series[field] = decode_feature(binaries[field], len(days))
            except ValueError as exc:
                errors.append(f'{field}:{exc}')
        row = {'symbol': symbol, 'declared_intervals': len(instruments[symbol]),
               'declared_first': min(a for a, b in instruments[symbol]),
               'declared_last': max(b for a, b in instruments[symbol]),
               'valid_price_bars': 0, 'all_price_missing_bars': 0,
               'partial_price_bars': 0, 'invalid_price_bars': 0,
               'invalid_volume_bars': 0, 'zero_volume_bars': 0,
               'invalid_factor_bars': 0, 'first_valid_date': '', 'last_valid_date': '',
               'field_errors': '; '.join(errors)}
        def value(field, index):
            if field not in series:
                return float('nan')
            offset, values = series[field]
            j = index - offset
            return values[j] if 0 <= j < len(values) else float('nan')
        for i in range(left, right):
            prices = [value(f, i) for f in PRICES]
            present = sum(not math.isnan(x) for x in prices)
            if not present:
                row['all_price_missing_bars'] += 1
                continue
            if present < 4:
                row['partial_price_bars'] += 1
                continue
            o, h, l, c = prices
            tolerance = max(1, abs(h)) * 1e-6
            if (not all(math.isfinite(x) and x > 0 for x in prices)
                    or l > min(o, c) + tolerance or h < max(o, c) - tolerance or l > h + tolerance):
                row['invalid_price_bars'] += 1
                continue
            row['valid_price_bars'] += 1
            row['first_valid_date'] = row['first_valid_date'] or days[i]
            row['last_valid_date'] = days[i]
            yearly[days[i][:4]] += 1
            daily[days[i]] += 1
            volume, factor = value('volume', i), value('factor', i)
            row['invalid_volume_bars'] += int(not math.isfinite(volume) or volume < 0)
            row['zero_volume_bars'] += int(volume == 0)
            row['invalid_factor_bars'] += int(not math.isfinite(factor) or factor <= 0)
        row['quality_flag'] = bool(errors or row['partial_price_bars'] or row['invalid_price_bars']
                                   or row['invalid_volume_bars'] or row['invalid_factor_bars'])
        rows.append(row)
        if number % 500 == 0:
            print(f'Inspected actual feature bytes for {number}/{len(mainboard)} mainboard codes', flush=True)
    valid_count = sum(r['valid_price_bars'] for r in rows)
    if valid_count == 0:
        raise ValueError('No valid mainboard OHLC observations in requested period')
    flagged = sum(r['quality_flag'] for r in rows)
    summary = {
        'status': 'DATA_RECEIVED_WITH_QUALITY_FLAGS' if flagged else 'DATASET_STRUCTURAL_CHECK_PASSED',
        'archive_acquired_and_identity_verified': True,
        'calendar_start': days[0], 'calendar_end': days[-1],
        'calendar_length': len(days), 'requested_start': config['requested_start'],
        'requested_end': config['requested_end'], 'actual_requested_days': right - left,
        'instrument_symbols': len(instruments), 'mainboard_symbols': len(mainboard),
        'mainboard_symbols_with_valid_prices': sum(r['valid_price_bars'] > 0 for r in rows),
        'mainboard_symbols_without_requested_prices': sum(r['valid_price_bars'] == 0 for r in rows),
        'quality_flagged_symbols': flagged, 'valid_mainboard_bars': valid_count,
        'unlisted_mainboard_feature_symbols': len(feature_bytes),
        'yearly_valid_price_bars': dict(sorted(yearly.items())),
        'daily_valid_price_symbols': dict(sorted(daily.items())),
        'official_historical_market_coverage': None,
        'historical_st_delisting_verified': False, 'independent_price_source_verified': False,
        'backtest_performed': False, 'strategy_ready': False,
        'member_count': len(seen), 'expanded_archive_bytes': expanded,
        'limitations': ['Dataset inventory is not the official historical market denominator.',
                       'Missing OHLC dates are not inferred to be suspensions or delistings.',
                       'Qlib adjusted/normalized prices are not raw RMB execution prices.',
                       'SHA-256 validates bytes, not economic accuracy or trading profitability.']}
    return summary, rows


def save_report(output: Path, summary: dict, rows: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if rows:
        with (output / 'mainboard_coverage.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = ['# A股历史数据云端核验', '', f"状态：{summary['status']}", '',
             '**这份结果不是回测、不是全市场验证通过，也不包含任何收益或胜率承诺。**', '']
    labels = {'calendar_start': '实际日历起点', 'calendar_end': '实际行情日历截止',
              'mainboard_symbols': '数据集列出的主板代码数',
              'mainboard_symbols_with_valid_prices': '请求期间含有效OHLC的主板代码数',
              'mainboard_symbols_without_requested_prices': '请求期间无有效OHLC的主板代码数',
              'valid_mainboard_bars': '有效主板股票日线数', 'quality_flagged_symbols': '带质量警示的代码数',
              'error': '失败原因'}
    for key, label in labels.items():
        if key in summary:
            lines.append(f'- {label}：{summary[key]}')
    lines += ['', '完整逐股清单见 mainboard_coverage.csv。官方历史证券覆盖率仍为未知；'
              'ST、退市、公司行为和独立来源准确性尚未核验。', '',
              '主分支及现有复盘任务未由此工作流修改；无券商连接、无下单、无付费模型调用。']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    summary = {'status': 'FAILED', 'backtest_performed': False, 'strategy_ready': False,
               'archive_acquired_and_identity_verified': False,
               'official_historical_market_coverage': None}
    rows = []
    try:
        config = json.loads(args.config.read_text(encoding='utf-8'))
        args.work_dir.mkdir(parents=True, exist_ok=True)
        args.output.mkdir(parents=True, exist_ok=True)
        paths = {}
        for kind, filename in [('manifest', 'qlib_bin.manifest.json'), ('archive', 'qlib_bin.tar.gz')]:
            path = args.work_dir / filename
            download(config[f'{kind}_url'], path, config[f'{kind}_size'], config[f'{kind}_sha256'])
            paths[kind] = path
        summary['archive_acquired_and_identity_verified'] = True
        manifest = json.loads(paths['manifest'].read_text(encoding='utf-8'))
        if (manifest.get('release_tag') != config['release_tag']
                or manifest.get('archive_size_bytes') != config['archive_size']
                or manifest.get('archive_sha256', '').removeprefix('sha256:') != config['archive_sha256']
                or manifest.get('target_trade_date') != config['requested_end']):
            raise ValueError('Pinned configuration and actual provenance manifest disagree')
        summary, rows = inspect_archive(paths['archive'], config, manifest)
        summary['source'] = config
        summary['provenance_manifest'] = manifest
        (args.output / 'source_manifest.json').write_bytes(paths['manifest'].read_bytes())
    except Exception as exc:
        summary['error'] = f'{type(exc).__name__}: {exc}'
    summary['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    save_report(args.output, summary, rows)
    print(json.dumps({k: v for k, v in summary.items() if k != 'daily_valid_price_symbols'}, ensure_ascii=False, indent=2))
    return 0 if summary['status'] == 'DATASET_STRUCTURAL_CHECK_PASSED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
