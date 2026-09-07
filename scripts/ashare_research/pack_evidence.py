"""Losslessly recompress CSV evidence; never round numbers or remove records."""
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import sys


def digest_open(opener, path):
    h=hashlib.sha256()
    with opener(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def compact(root: Path):
    records=[]
    for src in sorted(root.glob('*.csv.gz')):
        dst=src.with_suffix('.xz')
        if dst.exists(): raise FileExistsError(dst)
        old_size=src.stat().st_size
        with gzip.open(src,'rb') as reader,lzma.open(dst,'wb',preset=6) as writer:
            shutil.copyfileobj(reader,writer,1024*1024)
        before=digest_open(gzip.open,src);after=digest_open(lzma.open,dst)
        if before!=after:
            dst.unlink()
            raise ValueError('Decoded evidence changed during compression')
        if dst.stat().st_size<old_size:
            src.unlink();chosen=dst
        else:
            dst.unlink();chosen=src
        records.append({'input':src.name,'output':chosen.name,'original_bytes':old_size,
          'new_bytes':chosen.stat().st_size,'decoded_sha256':before,'decoded_bytes_verified':True})
    return records


if __name__=='__main__':
    root=Path(sys.argv[1]);rows=compact(root)
    (root/'compression.json').write_text(json.dumps(rows,indent=2))
    print(json.dumps(rows,indent=2))
