"""Verify final embedded package versions in both distribution formats."""
import email.parser
import sys
import tarfile
import zipfile
from pathlib import Path

expected = sys.argv[1]
wheel, = Path('dist').glob('*.whl')
sdist, = Path('dist').glob('*.tar.gz')
with zipfile.ZipFile(wheel) as archive:
    metadata, = (name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
    if email.parser.Parser().parsestr(archive.read(metadata).decode())['Version'] != expected:
        raise ValueError('wheel version mismatch')
    if f'__version__ = "{expected}"' not in archive.read('gh_address_cr/__init__.py').decode():
        raise ValueError('embedded runtime version mismatch')
with tarfile.open(sdist) as archive:
    member, = (member for member in archive.getmembers() if member.name.count('/') == 1 and member.name.endswith('/PKG-INFO'))
    if email.parser.Parser().parsestr(archive.extractfile(member).read().decode())['Version'] != expected:
        raise ValueError('sdist version mismatch')
