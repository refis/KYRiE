"""Build a private-data-free source snapshot using an explicit source allowlist."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile
from version import __version__, SNAPSHOT_DATE

DIRECTORIES = ('capture','config','docs','gui','hook','ipc','parser','reconstruction','storage','tests','tools','.github')
ROOT_FILES = ('main.py','events.py','version.py','README.md','DEVELOPMENT.md','CONTRIBUTING.md','SECURITY.md',
              'requirements.txt','requirements-lock.txt','PacketLength.txt','.gitignore','LICENSE','NOTICE',
              '.cursor/rules/project.mdc','client/README.md','.github/CODEOWNERS')
SUFFIXES = {'.py','.md','.json','.txt','.yml','.yaml'}
LOCAL_DIRECTORIES = {'logs', '.reference', 'dist', '.venv', '__pycache__', '.git', '.pytest_cache'}


def source_file_names(root):
    if (root / '.git').exists():
        try:
            result = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'])
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError('Cannot list tracked snapshot sources') from exc
        return result.decode('utf-8').split('\0')
    manifest = root / 'SNAPSHOT.json'
    if manifest.is_file():
        return [item['path'] for item in json.loads(manifest.read_text(encoding='utf-8'))['files']]
    raise ValueError('Snapshot sources require a Git checkout or an existing SNAPSHOT.json')


def require_versioned_readme(root):
    """Refuse packaging when the root README banner lags version.py."""
    readme = root / 'README.md'
    if not readme.is_file():
        raise ValueError('Snapshot source root is incomplete')
    first = next((line.strip() for line in readme.read_text(encoding='utf-8').splitlines() if line.strip()), '')
    expected = f'# KYRiE v{__version__} (Windows)'
    if first != expected:
        raise ValueError(f'Root README.md must start with {expected!r} (found {first!r})')
    body = readme.read_text(encoding='utf-8')
    if f'docs/releases/v{__version__}.md' not in body:
        raise ValueError(f'Root README.md must link docs/releases/v{__version__}.md')


def build_snapshot(root, output_dir):
    root = Path(root).resolve()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', __version__):
        raise ValueError('Invalid snapshot version')
    if not (root/'main.py').is_file():
        raise ValueError('Snapshot source root is incomplete')
    require_versioned_readme(root)
    files = {}
    candidates = []
    for name in source_file_names(root):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid snapshot source path')
        if not relative.parts or LOCAL_DIRECTORIES.intersection(relative.parts):
            continue
        if (relative.as_posix() in ROOT_FILES
                or (relative.parts[0] in DIRECTORIES and relative.suffix in SUFFIXES)):
            candidates.append(root / relative)
    total = 0
    for path in sorted(set(candidates)):
        if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root))
                or not path.resolve().is_relative_to(root)):
            raise ValueError('Source file resolves outside snapshot root')
        name = path.relative_to(root).as_posix()
        if name == 'config/ignorepacket.json':
            continue  # Local exclusions; never ship or overwrite with empty defaults.
        if name == 'config/user_settings.json':
            continue  # Local GUI preference profile; never ship machine-specific settings.
        if not path.is_file():
            raise ValueError(f'Snapshot source is missing: {name}')
        size = path.stat().st_size
        if size > 16*1024*1024 or total + size > 64*1024*1024:
            raise ValueError('Source snapshot size limit reached')
        data = path.read_bytes()
        if len(data) != size:
            raise ValueError('Source changed while building snapshot')
        files[name] = data
        total += size
    # Do not inject empty ignorepacket.json: extracting a ZIP must not wipe local presets.
    # Tracked template is config/ignorepacket.example.json; runtime seeds via IgnorePacket.ensure_default_file.
    manifest = dict(kind='source_snapshot',version=__version__,snapshot_date=SNAPSHOT_DATE,
        includes_private_capture_data=False, local_preferences_excluded=True,
        excluded=['logs/','client EXE and extracted definitions','.reference/','packets.sqlite3*',
                  'root generated NPC code','caches','dist/',
                  'config/user_settings.json','config/ignorepacket.json'],
        files=[dict(path=name,size=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in sorted(files.items())])
    files['SNAPSHOT.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True,exist_ok=True)
    stem = 'KYRiE-v'+__version__+'-source'
    archive = output_dir/(stem+'.zip')
    checksum = output_dir/(stem+'.zip.sha256')
    if archive.exists() or checksum.exists():
        raise FileExistsError('Snapshot already exists; choose a new output directory')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_dir,suffix='.tmp',delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as bundle:
            for name,data in sorted(files.items()):
                info = zipfile.ZipInfo('KYRiE-v'+__version__+'/'+name,date_time=(1980,1,1,0,0,0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                bundle.writestr(info,data)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary,archive)
        with checksum.open('x',encoding='ascii',newline='\n') as stream:
            stream.write(digest+'  '+archive.name+'\n')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return dict(archive=str(archive),checksum=str(checksum),sha256=digest,files=len(manifest['files']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='dist')
    args = parser.parse_args()
    result = build_snapshot(Path(__file__).resolve().parents[1],args.output_dir)
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
