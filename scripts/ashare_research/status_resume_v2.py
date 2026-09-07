"""Bounded continuation of historical-state acquisition, not a trading system.
Completed full responses are reused; each new complete response is atomically
checkpointed. Unknown dates remain unknown. No change to buy/sell rules.
"""
from __future__ import annotations
import argparse, csv, gzip, hashlib, json, lzma, multiprocessing as mp
import signal, socket, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from historical_status import align_status, deterministic_order, FIELDS, _alarm, _query, _login


def retry_query(query, reconnect, sleep=time.sleep):
    """One fresh-session retry; never convert an exception into an empty result."""
    for attempt in range(2):
        try:
            return query(), attempt + 1
        except Exception:
            if attempt == 1:
                raise
            sleep(1.)
            reconnect()
    raise AssertionError('unreachable')


def read_rows(path):
    with gzip.open(path, 'rt', newline='') as f:
        r = csv.reader(f)
        if next(r) != FIELDS.split(','):
            raise ValueError('Unexpected saved fields')
        return list(r)


def save_rows(root, symbol, rows, days):
    if not rows:
        raise ValueError('Empty response is not a completed history')
    align_status(rows, days, symbol)
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    target = root / (symbol + '.csv.gz')
    partial = target.with_suffix(target.suffix + '.partial')
    with gzip.open(partial, 'wt', newline='') as f:
        w = csv.writer(f); w.writerow(FIELDS.split(',')); w.writerows(rows)
    if read_rows(partial) != rows:
        raise ValueError('Checkpoint round-trip mismatch')
    partial.replace(target)
    return target


def merge_rows(records, symbol, rows):
    if symbol in records and records[symbol] != rows:
        raise ValueError('Conflicting complete history: ' + symbol)
    records[symbol] = rows


def remaining(symbols, records):
    return [s for s in deterministic_order(symbols) if s not in records]


def load_saved(root, days):
    records = {}
    for path in sorted(Path(root).glob('*.csv.gz')):
        symbol = path.name.split('.')[0]
        rows = read_rows(path); align_status(rows, days, symbol)
        if not rows:
            raise ValueError('Empty saved history')
        merge_rows(records, symbol, rows)
    return records


def seed_history(root, days):
    """Only provider-accepted full histories, checked against original matrices."""
    records = {}; universe = set(); smoke = []; raw_rows = 0
    for matrix in sorted(Path(root).rglob('status_*.npz')):
        number = matrix.stem.split('_')[-1]; folder = matrix.parent
        fetch = json.loads((folder / f'fetch_{number}.json').read_text())
        wanted = {r['symbol']: r for r in fetch if r['status'] == 'received'}
        grouped = {s: [] for s in wanted}
        with lzma.open(folder / f'provider_records_{number}.csv.xz', 'rt', newline='') as f:
            reader = csv.reader(f)
            if next(reader) != FIELDS.split(','):
                raise ValueError('Seed fields changed')
            for row in reader:
                symbol = row[1].replace('.', '').upper()
                if symbol in grouped:
                    grouped[symbol].append(row)
        with np.load(matrix, allow_pickle=False) as z:
            if list(z['days']) != days:
                raise ValueError('Seed calendar mismatch')
            symbols = list(map(str, z['symbols'])); universe.update(symbols)
            for i, symbol in enumerate(symbols):
                if symbol not in wanted:
                    continue
                rows = grouped[symbol]
                if len(rows) != int(wanted[symbol]['rows']) or not rows:
                    raise ValueError('Missing or incomplete accepted response')
                st, trade, _ = align_status(rows, days, symbol)
                np.testing.assert_array_equal(st, z['isST'][i])
                np.testing.assert_array_equal(trade, z['tradestatus'][i])
                merge_rows(records, symbol, rows); raw_rows += len(rows)
        p = folder / f'smoke_{number}.json'
        if p.exists():
            smoke.extend(json.loads(p.read_text()))
    if not universe:
        raise ValueError('No seed matrices found')
    return records, universe, smoke, raw_rows


def load_merged(root, days):
    root = Path(root)
    if not (root / 'states.npz').exists():
        return {}
    accepted = {r['symbol']: r for r in json.loads((root / 'accepted.json').read_text())}
    grouped = {s: [] for s in accepted}
    with lzma.open(root / 'provider_records.csv.xz', 'rt', newline='') as f:
        reader = csv.reader(f)
        if next(reader) != FIELDS.split(','):
            raise ValueError('Merged fields differ')
        for row in reader:
            symbol = row[1].replace('.', '').upper()
            if symbol not in grouped:
                raise ValueError('Undeclared merged record')
            grouped[symbol].append(row)
    with np.load(root / 'states.npz', allow_pickle=False) as z:
        if list(z['days']) != days:
            raise ValueError('Merged calendar differs')
        pos = {str(s): i for i, s in enumerate(z['symbols'])}
        for symbol, rows in grouped.items():
            if not rows or len(rows) != accepted[symbol]['rows']:
                raise ValueError('Incomplete merged response')
            st, tr, _ = align_status(rows, days, symbol)
            np.testing.assert_array_equal(st, z['isST'][pos[symbol]])
            np.testing.assert_array_equal(tr, z['tradestatus'][pos[symbol]])
    return grouped


def verify_seed_hashes(root, hashes):
    for relative, expected in hashes.items():
        matches = [p for p in Path(root).rglob(Path(relative).name)
                   if str(p).replace('\\', '/').endswith(relative)]
        if len(matches) != 1:
            raise ValueError('Missing/ambiguous seed file: ' + relative)
        if hashlib.sha256(matches[0].read_bytes()).hexdigest() != expected:
            raise ValueError('Seed SHA-256 mismatch: ' + relative)


def worker(number, symbols, days, folder, budget):
    """Moderate concurrency; bounded retries, reconnects and request deadlines."""
    signal.signal(signal.SIGALRM, _alarm); socket.setdefaulttimeout(15)
    import baostock as bs
    root = Path(folder); raw = root / 'new_records'; raw.mkdir(exist_ok=True)
    deadline = time.monotonic() + budget; consecutive = 0; completed = 0
    def reconnect():
        try:
            signal.alarm(5); bs.logout()
        except Exception:
            pass
        finally:
            signal.alarm(0)
        _login(bs)
    connected = False
    with (root / f'worker_{number}.jsonl').open('w') as log:
        for symbol in symbols:
            if time.monotonic() >= deadline or consecutive >= 6:
                break
            record = {'symbol': symbol, 'worker': number}
            try:
                if not connected:
                    reconnect(); connected = True
                rows, attempts = retry_query(
                    lambda: _query(bs, symbol, days[0], days[-1]), reconnect)
                if rows:
                    path = save_rows(raw, symbol, rows, days)
                    record.update(status='received', rows=len(rows), attempts=attempts,
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                    completed += 1
                else:
                    record.update(status='empty', rows=0, attempts=attempts)
                consecutive = 0
            except Exception as exc:
                connected = False; consecutive += 1
                record.update(status='error', reason=f'{type(exc).__name__}: {exc}')
            log.write(json.dumps(record, ensure_ascii=False) + '\n'); log.flush()
            if completed and completed % 100 == 0:
                print(f'Worker {number}: {completed} complete histories saved', flush=True)
            time.sleep(.10)
    try:
        signal.alarm(5); bs.logout()
    except Exception:
        pass
    finally:
        signal.alarm(0)


def collect(a):
    a.output.mkdir(parents=True, exist_ok=True)
    config = json.loads(a.seeds.read_text()); merged = {}; universe = set(); allsmoke = []
    checks = []
    first = next(a.seed_a.rglob('status_0.npz'))
    with np.load(first, allow_pickle=False) as z:
        days = list(map(str, z['days']))
    if days[0] != '2000-01-04' or days[-1] != '2026-09-04':
        raise ValueError('Research cutoff differs')
    for label, root in [('A', a.seed_a), ('T', a.seed_t)]:
        verify_seed_hashes(root, config[label]['files'])
        records, symbols, smoke, n = seed_history(root, days)
        for s, rows in records.items():
            merge_rows(merged, s, rows)
        universe.update(symbols); allsmoke += smoke
        checks.append(dict(seed=label, histories=len(records), rows=n,
                           artifact_id=config[label]['artifact_id']))
    initial = len(merged)
    if initial != config['expected_seed_histories'] or len(universe) != 3485:
        raise ValueError('Unexpected seed coverage')
    # A repeated local/cloud invocation reuses atomically saved successes as well.
    for s, rows in load_saved(a.output / 'new_records', days).items():
        merge_rows(merged, s, rows)
    for root in [a.output/'merged_status'] + list(a.resume_from):
        for s, rows in load_merged(root, days).items():
            merge_rows(merged, s, rows)
    before_network = len(merged)
    order = remaining(universe, merged)
    (a.output / 'frozen_pending.json').write_text(json.dumps(order))
    print(f'Reused {len(merged)} full histories; pending {len(order)}', flush=True)
    context = mp.get_context('spawn'); processes = []
    for i in range(a.workers):
        p = context.Process(target=worker,
                            args=(i, order[i::a.workers], days, str(a.output), a.seconds))
        p.start(); processes.append(p)
    end = time.monotonic() + a.seconds + 65
    for p in processes:
        p.join(max(0., end - time.monotonic()))
        if p.is_alive():
            p.kill(); p.join()
    for s, rows in load_saved(a.output / 'new_records', days).items():
        merge_rows(merged, s, rows)
    symbols = sorted(universe); si = {s: i for i, s in enumerate(symbols)}
    st = np.full((len(symbols), len(days)), -1, np.int8); tr = st.copy()
    status_root = a.output / 'merged_status'; status_root.mkdir(exist_ok=True)
    accepted = []
    with lzma.open(status_root / 'provider_records.csv.xz', 'wt', newline='') as f:
        w = csv.writer(f); w.writerow(FIELDS.split(','))
        for s in sorted(merged):
            x, y, meta = align_status(merged[s], days, s)
            st[si[s]] = x; tr[si[s]] = y; w.writerows(merged[s])
            accepted.append(dict(symbol=s, status='received', **meta))
    np.savez_compressed(status_root / 'states.npz', symbols=np.array(symbols),
                        days=np.array(days), isST=st, tradestatus=tr)
    (status_root / 'accepted.json').write_text(json.dumps(accepted))
    pending = remaining(symbols, merged)
    (status_root / 'remaining.json').write_text(json.dumps(pending))
    events = []
    for p in a.output.glob('worker_*.jsonl'):
        events += [json.loads(line) for line in p.read_text().splitlines() if line]
    status_counts = Counter(r['status'] for r in events)
    event_symbols = {r['symbol'] for r in events if r['status']=='received'}
    if not event_symbols.issubset(merged):
        raise ValueError('Journal references missing completed file')
    receipt = dict(study='STATUS_RESUME_V2', requested_codes=len(symbols),
                   initial_histories=initial, histories_before_network=before_network, original_histories=290,
                   reused_other_export=initial-290, received_codes=len(merged),
                   newly_downloaded=len(merged)-before_network, pending_codes=len(pending),
                   provider_rows=sum(len(r) for r in merged.values()),
                   status_counts=dict(status_counts), worker_exit_codes=[p.exitcode for p in processes],
                   seed_checks=checks, smoke_controls=allsmoke,
                   smoke_ok=bool(allsmoke) and all(s.get('passed') for s in allsmoke),
                   smoke_controls_are_reused=True, fields=FIELDS,
                   requested_start=days[0], requested_end=days[-1],
                   historical_publication_timestamps_verified=False,
                   native_ths_verified=False, trade_ready=False,
                   finished_at_utc=datetime.now(timezone.utc).isoformat())
    (a.output / 'acquisition.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    # Exact provider records already exist in one compressed, independently readable file.
    # Keep journals/hashes; remove only duplicate per-symbol copies after verification.
    with lzma.open(status_root / 'provider_records.csv.xz', 'rt', newline='') as f:
        r = csv.reader(f)
        if next(r) != FIELDS.split(','): raise ValueError('Consolidation header changed')
        verified = 0
        for symbol in sorted(merged):
            for row in merged[symbol]:
                if next(r) != row: raise ValueError('Consolidation changed field text')
                verified += 1
        if next(r, None) is not None: raise ValueError('Unexpected consolidation rows')
    if verified != receipt['provider_rows']:
        raise ValueError('Consolidation omitted rows')
    (a.output / 'consolidation.json').write_text(json.dumps({'rows': verified,'lossless':True}))
    for p in (a.output / 'new_records').glob('*.csv.gz'):
        p.unlink()
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return days, symbols, st, tr, receipt, accepted


def main():
    p = argparse.ArgumentParser()
    for name in ('seed-a','seed-t','seeds','source','work','output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--resume-from', type=Path, action='append', default=[])
    p.add_argument('--workers', type=int, default=4, choices=[1,2,4])
    p.add_argument('--seconds', type=int, default=900)
    a = p.parse_args()
    if not 0 <= a.seconds <= 900:
        raise ValueError('Exceeded collection budget')
    days, symbols, st, tr, receipt, accepted = collect(a)
    import status_admission_study as old
    def frozen_states(requested, calendar, output):
        if requested != symbols or calendar != days:
            raise ValueError('Price/status universe or dates differ')
        states = {s: (st[i], tr[i]) for i,s in enumerate(symbols)}
        records = accepted + [dict(symbol=s,status='not_attempted',reason='still_unknown')
                              for s in symbols if s not in {r['symbol'] for r in accepted}]
        return states, receipt, records
    old.fetch_all = frozen_states
    sys.argv = ['status_admission_study.py','--source',str(a.source),
                '--work',str(a.work),'--output',str(a.output/'diagnostic')]
    code = old.main()
    if code:
        raise SystemExit(code)
    (a.output/'run_completed.json').write_text(json.dumps({'completed':True,'trade_ready':False}))

if __name__ == '__main__':
    main()
