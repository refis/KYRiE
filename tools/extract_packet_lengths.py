"""Static extractor for the observed Win32 four-immediate packet registrar.

This does not execute the client or claim to support arbitrary executables.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct

from parser.definitions import load_lengths


def executable_sections(data):
    if data[:2] != b'MZ' or len(data) < 64:
        raise ValueError('Not a PE executable')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if pe + 24 > len(data) or data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('Invalid PE header')
    machine, count = struct.unpack_from('<HH', data, pe + 4)
    size = struct.unpack_from('<H', data, pe + 20)[0]
    optional = pe + 24
    if machine != 0x14c or size < 32 or optional + size + count * 40 > len(data):
        raise ValueError('Expected bounded Win32/x86 PE headers')
    if struct.unpack_from('<H', data, optional)[0] != 0x10b:
        raise ValueError('Expected PE32 optional header')
    image_base = struct.unpack_from('<I', data, optional + 28)[0]
    sections = []
    for i in range(count):
        entry = optional + size + 40 * i
        virtual, rva, raw_size, offset = struct.unpack_from('<IIII', data, entry + 8)
        flags = struct.unpack_from('<I', data, entry + 36)[0]
        if raw_size and offset + raw_size > len(data):
            raise ValueError('Section exceeds executable bounds')
        if flags & 0x20000000 and raw_size:
            sections.append((offset, offset + raw_size, rva, image_base))
    return sections


def _push(data, pos, end):
    if pos >= end:
        raise ValueError('Truncated immediate')
    if data[pos] == 0x6a and pos + 2 <= end:
        return struct.unpack_from('<b', data, pos + 1)[0], pos + 2
    if data[pos] == 0x68 and pos + 5 <= end:
        return struct.unpack_from('<i', data, pos + 1)[0], pos + 5
    raise ValueError('Unsupported instruction')


def extract(data, minimum_records=100):
    sections = executable_sections(data)
    groups = defaultdict(list)
    for begin, end, rva, base in sections:
        for start in range(begin, end):
            if data[start] not in (0x6a, 0x68):
                continue
            try:
                pos, args = start, []
                for _ in range(4):
                    value, pos = _push(data, pos, end)
                    args.append(value)
                if pos + 7 > end or data[pos:pos + 3] != b'\x8b\xce\xe8':
                    continue
                target_rva = rva + pos - begin + 7 + struct.unpack_from('<i', data, pos + 3)[0]
                flag, minimum, length, packet_id = args
                if (flag not in (-1, 0, 1) or not 0 <= packet_id <= 65535
                        or not 2 <= minimum <= 65535
                        or length != -1 and not 2 <= length <= 65535):
                    continue
                if length != -1 and minimum > length:
                    continue
                # The registrar must also reside in an executable section.
                if not any(s[2] <= target_rva < s[2] + s[1] - s[0] for s in sections):
                    continue
                groups[base + target_rva].append(dict(packet_id=packet_id, length=length,
                    minimum_length=minimum, attribute=flag, file_offset=start,
                    instruction_va=base + rva + start - begin))
            except (ValueError, struct.error):
                continue
    candidates = [(target, rows) for target, rows in groups.items() if len(rows) >= minimum_records]
    if len(candidates) != 1:
        raise ValueError(f'Expected one registrar with >= {minimum_records} entries; found {len(candidates)}')
    target, rows = candidates[0]
    definitions, duplicates = {}, []
    for row in rows:
        pid = row['packet_id']
        if pid in definitions:
            duplicates.append(dict(packet_id=pid, previous=definitions[pid], replacement=row['length']))
        definitions[pid] = row['length']
    return definitions, dict(schema=1, method='x86-push4-mov-ecx-esi-call',
        source_sha256=hashlib.sha256(data).hexdigest(), registrar_va=target,
        registration_count=len(rows), unique_ids=len(definitions), duplicates=duplicates,
        limitations=['Static registration candidates; verify against actual receive traffic.',
                     'The final argument is retained as attribute; direction is not inferred.',
                     'File order is used for duplicate definitions; runtime branches are not evaluated.',
                     'No client execution, protected-code emulation or arbitrary-EXE support.'],
        registrations=rows)


def compare(old, new):
    return dict(
        added=[dict(packet_id=f'0x{pid:04X}', length=new[pid]) for pid in sorted(new.keys() - old.keys())],
        changed=[dict(packet_id=f'0x{pid:04X}', previous=old[pid], extracted=new[pid])
                 for pid in sorted(new.keys() & old.keys()) if old[pid] != new[pid]],
        absent_from_extraction=[dict(packet_id=f'0x{pid:04X}', previous=old[pid])
                                for pid in sorted(old.keys() - new.keys())])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('exe', type=Path)
    cli.add_argument('--baseline', type=Path, default=Path('PacketLength.txt'))
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.resolve() in (args.exe.resolve(), args.baseline.resolve()):
        cli.error('Output must differ from executable and baseline')
    data = args.exe.read_bytes()
    lengths, report = extract(data)
    report['source_file'] = args.exe.name
    report['comparison'] = compare(load_lengths(args.baseline), lengths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        '// Extracted static registration candidates; verify with receive traffic.\n'
        f'// Source SHA256: {report["source_sha256"]}\n' +
        ''.join(f'{pid:04X} {length}\n' for pid, length in sorted(lengths.items())), encoding='utf-8')
    report_path = args.output.with_suffix('.report.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(lengths)} IDs -> {args.output}; report -> {report_path}')


if __name__ == '__main__':
    main()
