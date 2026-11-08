"""Check immutable artifact archive metadata before Actions extracts any paths."""
from __future__ import annotations

import stat
import sys
import zipfile
from pathlib import Path


def validate(archive: Path) -> None:
    with zipfile.ZipFile(archive) as payload:
        names = set()
        files = set()
        entries = payload.infolist()
        if not entries:
            raise ValueError('empty release artifact archive')
        for entry in entries:
            name = entry.filename.removesuffix('/')
            pieces = name.split('/')
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if (not name or '\\' in name or '\x00' in name or ':' in name
                    or any(piece in {'', '.', '..'} for piece in pieces)
                    or mode not in {0, stat.S_IFREG, stat.S_IFDIR}):
                raise ValueError('unsafe release artifact archive entry')
            normalized = name.casefold()
            if normalized in names or any('/'.join(pieces[:index]).casefold() in files for index in range(1, len(pieces))):
                raise ValueError('duplicate or conflicting release artifact path')
            names.add(normalized)
            if not entry.is_dir():
                if any(previous.startswith(normalized + '/') for previous in names):
                    raise ValueError('conflicting release artifact file and directory')
                files.add(normalized)


if __name__ == '__main__':
    validate(Path(sys.argv[1]))
