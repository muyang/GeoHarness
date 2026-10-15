"""Package a verified official Electron archive; never include runtime user data."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    digest = hashlib.sha256()
    with args.archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    if not re.fullmatch(r'[a-f0-9]{64}', args.sha256) or digest.hexdigest() != args.sha256:
        raise SystemExit('Official archive SHA256 does not match')
    with zipfile.ZipFile(args.archive) as archive:
        if any(name.startswith('/') or '..' in Path(name).parts for name in archive.namelist()):
            raise SystemExit('Unsafe archive path')
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output/'GeoHarness.app'
    if target.exists():
        raise SystemExit('Output already exists; existing application preserved')
    here = Path(__file__).resolve().parent
    version = json.loads((here/'package.json').read_text())['version']
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(args.archive.resolve()), temporary], check=True)
        app = Path(temporary)/'Electron.app'
        info_path = app/'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        if info.get('CFBundleShortVersionString') != '44.7.2':
            raise SystemExit('Unexpected Electron version')
        info.update(CFBundleName='GeoHarness', CFBundleDisplayName='GeoHarness', CFBundleIdentifier='org.geonexus.geoharness.preview', CFBundleShortVersionString=version, CFBundleVersion=version)
        info_path.write_bytes(plistlib.dumps(info))
        resources = app/'Contents/Resources/app'
        resources.mkdir()
        for name in ['package.json', 'main.cjs', 'policy.cjs', 'offline.html']:
            shutil.copy2(here/name, resources/name)
        (app/'Contents/Resources/default_app.asar').unlink(missing_ok=True)
        shutil.move(app, target)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(target)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(target)], check=True)
    (args.output/'package-manifest.json').write_text(json.dumps({'app':target.name,'version':version,'electron':'44.7.2','archive_sha256':args.sha256,'runtime_url':'http://127.0.0.1:8810/','bundles_backend':False,'signature':'local ad-hoc; not notarized'}, indent=2))
    print(target)


if __name__ == '__main__':
    main()
