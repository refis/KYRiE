import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.build_snapshot import build_snapshot, require_versioned_readme
from version import __version__, SNAPSHOT_DATE

REPO = Path(__file__).resolve().parents[2]


def versioned_readme(extra=''):
    return (f'# KYRiE v{__version__} (Windows)\n\n'
            f'- [notes](docs/releases/v{__version__}.md)\n' + extra)


class SnapshotTests(unittest.TestCase):
    def test_repo_readme_and_release_notes_match_version_py(self):
        require_versioned_readme(REPO)
        notes = REPO / 'docs' / 'releases' / f'v{__version__}.md'
        self.assertTrue(notes.is_file(), f'missing {notes.name}')
        index = (REPO / 'docs' / 'README.md').read_text(encoding='utf-8')
        self.assertIn(f'releases/v{__version__}.md', index)
        readme = (REPO / 'README.md').read_text(encoding='utf-8')
        self.assertIn(f'# KYRiE v{__version__} (Windows)', readme.splitlines()[0])
        self.assertRegex(SNAPSHOT_DATE, r'^\d{4}-\d{2}-\d{2}$')
        root_manifest = REPO / 'SNAPSHOT.json'
        if root_manifest.is_file():
            manifest = json.loads(root_manifest.read_text(encoding='utf-8'))
            self.assertEqual(manifest.get('version'), __version__)
            self.assertEqual(manifest.get('snapshot_date'), SNAPSHOT_DATE)

    def test_build_snapshot_rejects_stale_readme_banner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            root.mkdir()
            (root / 'main.py').write_text('pass\n', encoding='utf-8')
            (root / 'PacketLength.txt').write_text('0000 2\n', encoding='utf-8')
            (root / 'README.md').write_text('# KYRiE v0.0.0 (Windows)\n\nold\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Root README.md must start with'):
                build_snapshot(root, Path(folder) / 'out')

    def test_manifest_reproducibility_and_private_data_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';root.mkdir()
            for name in ('main.py','PacketLength.txt','packets.sqlite3','all-placed-npcs-merged.txt'):
                (root/name).write_text('sample',encoding='utf-8')
            (root/'README.md').write_text(versioned_readme(),encoding='utf-8')
            for directory,name in (('config','ignorepacket.json'),('logs','capture.jsonl'),
                                   ('client','private.exe'),('.reference','source.py'),('gui','view.py')):
                (root/directory).mkdir(exist_ok=True)
                (root/directory/name).write_text('private' if directory!='gui' else 'source',encoding='utf-8')
            (root/'config/user_settings.json').write_text('{"version":1,"capture_send":false}',encoding='utf-8')
            original=(root/'config/ignorepacket.json').read_bytes()
            original_settings=(root/'config/user_settings.json').read_bytes()
            first=build_snapshot(root,Path(folder)/'one')
            second=build_snapshot(root,Path(folder)/'two')
            self.assertEqual(first['sha256'],second['sha256'])
            with zipfile.ZipFile(first['archive']) as bundle:
                prefix='KYRiE-v'+__version__+'/'
                names={n.removeprefix(prefix) for n in bundle.namelist()}
                self.assertEqual(names,{'main.py','README.md','PacketLength.txt','gui/view.py','config/ignorepacket.json','SNAPSHOT.json'})
                self.assertNotIn('config/user_settings.json',names)
                manifest=json.loads(bundle.read(prefix+'SNAPSHOT.json'))
                self.assertIn('config/user_settings.json',manifest['excluded'])
                for row in manifest['files']:
                    data=bundle.read(prefix+row['path'])
                    self.assertEqual(hashlib.sha256(data).hexdigest(),row['sha256'])
                    self.assertEqual(len(data),row['size'])
                self.assertEqual(json.loads(bundle.read(prefix+'config/ignorepacket.json'))['npc_names'],[])
            self.assertEqual((root/'config/ignorepacket.json').read_bytes(),original)
            self.assertEqual((root/'config/user_settings.json').read_bytes(),original_settings)
            with self.assertRaises(FileExistsError):build_snapshot(root,Path(folder)/'one')

    def test_management_docs_and_github_templates_are_packaged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';root.mkdir()
            for name in ('main.py','PacketLength.txt','CONTRIBUTING.md','SECURITY.md','NOTICE'):
                (root/name).write_text(name,encoding='utf-8')
            (root/'README.md').write_text(versioned_readme(),encoding='utf-8')
            github=root/'.github'
            (github/'ISSUE_TEMPLATE').mkdir(parents=True)
            (github/'workflows').mkdir(parents=True)
            (github/'CODEOWNERS').write_text('* @refis\n',encoding='utf-8')
            (github/'pull_request_template.md').write_text('pr',encoding='utf-8')
            (github/'ISSUE_TEMPLATE'/'bug.yml').write_text('name: Bug\n',encoding='utf-8')
            (github/'workflows'/'ci.yml').write_text('name: CI\n',encoding='utf-8')
            (root/'logs').mkdir();(root/'logs'/'capture.jsonl').write_text('secret',encoding='utf-8')
            result=build_snapshot(root,Path(folder)/'out')
            with zipfile.ZipFile(result['archive']) as bundle:
                prefix='KYRiE-v'+__version__+'/'
                names={n.removeprefix(prefix) for n in bundle.namelist()}
            self.assertTrue({'CONTRIBUTING.md','SECURITY.md','NOTICE',
                             '.github/CODEOWNERS','.github/pull_request_template.md',
                             '.github/ISSUE_TEMPLATE/bug.yml','.github/workflows/ci.yml'} <= names)
            self.assertNotIn('logs/capture.jsonl',names)
