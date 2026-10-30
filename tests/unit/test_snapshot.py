import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.build_snapshot import build_snapshot
from version import __version__


class SnapshotTests(unittest.TestCase):
    def test_manifest_reproducibility_and_private_data_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';root.mkdir()
            for name in ('main.py','README.md','PacketLength.txt','packets.sqlite3','all-placed-npcs-merged.txt'):
                (root/name).write_text('sample',encoding='utf-8')
            for directory,name in (('config','ignorepacket.json'),('logs','capture.jsonl'),
                                   ('client','private.exe'),('.reference','source.py'),('gui','view.py')):
                (root/directory).mkdir(exist_ok=True)
                (root/directory/name).write_text('private' if directory!='gui' else 'source',encoding='utf-8')
            original=(root/'config/ignorepacket.json').read_bytes()
            first=build_snapshot(root,Path(folder)/'one')
            second=build_snapshot(root,Path(folder)/'two')
            self.assertEqual(first['sha256'],second['sha256'])
            with zipfile.ZipFile(first['archive']) as bundle:
                prefix='KYRiE-v'+__version__+'/'
                names={n.removeprefix(prefix) for n in bundle.namelist()}
                self.assertEqual(names,{'main.py','README.md','PacketLength.txt','gui/view.py','config/ignorepacket.json','SNAPSHOT.json'})
                manifest=json.loads(bundle.read(prefix+'SNAPSHOT.json'))
                for row in manifest['files']:
                    data=bundle.read(prefix+row['path'])
                    self.assertEqual(hashlib.sha256(data).hexdigest(),row['sha256'])
                    self.assertEqual(len(data),row['size'])
                self.assertEqual(json.loads(bundle.read(prefix+'config/ignorepacket.json'))['npc_names'],[])
            self.assertEqual((root/'config/ignorepacket.json').read_bytes(),original)
            with self.assertRaises(FileExistsError):build_snapshot(root,Path(folder)/'one')
