"""PACKET_ZC_MAPPROPERTY symbols and manual-review memos for map type/flags.

0x02E7 carries type + mapInfoTable[MAPPROPERTY_*]. Current JP captures often use
0x01D6 (type) / 0x099B (type+flags u32) instead. flags bit labels are review guesses
only — not proof that 099B packs mapInfoTable bits.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MAX_SOURCE_BYTES = 256 * 1024
ZC_SYMBOLS_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZC_SYMBOLS = ROOT / 'config' / 'zc_mapproperty_symbols.json'
DEFAULT_MAPTYPE_CATALOG = ROOT / 'config' / 'maptype_property_catalog.json'

# Fixed layout from PACKET_ZC_MAPPROPERTY samples: PacketType + Length + type + 27 table bytes.
ZC_MAPPROPERTY_ID = 0x2E7
ZC_MAPPROPERTY_HEADER = 6
ZC_MAPPROPERTY_TABLE_LEN = 27  # MAPPROPERTY_LAST == 0x1B


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_zc_mapproperty_document(text: str) -> dict:
    """Extract MAPTYPE / MAPPROPERTY enums and optional 33-byte hex samples."""
    if not isinstance(text, str) or not text:
        raise ValueError('PACKET_ZC_MAPPROPERTY text is required')
    maptypes = {}
    maptype_last = None
    samples = {}
    seen_type_symbols = set()
    for match in re.finditer(
            r'MAPTYPE_([A-Z0-9_]+)\s*=\s*(0x[0-9A-Fa-f]+)\s*,?\s*(?://(.*))?$', text, re.M):
        name, value = match.group(1), int(match.group(2), 16)
        if name == 'LAST':
            maptype_last = value
            continue
        symbol = 'MAPTYPE_' + name
        if not 0 <= value <= 0xFFFF or symbol in seen_type_symbols or str(value) in maptypes:
            raise ValueError('Invalid or duplicate MAPTYPE entry')
        seen_type_symbols.add(symbol)
        key = str(value)
        comment = (match.group(3) or '').strip()
        # Prefer preceding // map notes on prior lines via comment only (.gat in same comment)
        map_notes = re.findall(r'([0-9A-Za-z_@.-]+\.gat)', comment)
        entry = dict(id=value, symbol=symbol, map_name_notes=map_notes)
        hex_runs = re.findall(r'(?:[0-9A-Fa-f]{2}\s*){20,}', comment)
        if hex_runs:
            raw = bytes.fromhex(''.join(hex_runs[0].split()))
            if len(raw) >= ZC_MAPPROPERTY_HEADER + 1:
                samples[key] = dict(
                    packet_hex=raw.hex(),
                    length=int.from_bytes(raw[2:4], 'little') if len(raw) >= 4 else None,
                    type=int.from_bytes(raw[4:6], 'little') if len(raw) >= 6 else None,
                    table_bytes=list(raw[6:]),
                )
        maptypes[key] = entry
    # Capture // map notes on the line immediately before a MAPTYPE when comment lacked .gat
    prior_maps = None
    for line in text.splitlines():
        note_maps = re.findall(r'([0-9A-Za-z_@.-]+\.gat)', line) if line.lstrip().startswith('//') else None
        header = re.search(r'MAPTYPE_([A-Z0-9_]+)\s*=\s*(0x[0-9A-Fa-f]+)', line)
        if header and prior_maps:
            key = str(int(header.group(2), 16))
            if key in maptypes and not maptypes[key]['map_name_notes']:
                maptypes[key]['map_name_notes'] = prior_maps
        if note_maps is not None:
            prior_maps = note_maps or prior_maps
        elif header:
            prior_maps = None
    properties = {}
    property_last = None
    seen_prop_symbols = set()
    for match in re.finditer(r'MAPPROPERTY_([A-Z0-9_]+)\s*=\s*(0x[0-9A-Fa-f]+)', text):
        name, value = match.group(1), int(match.group(2), 16)
        if name == 'LAST':
            property_last = value
            continue
        symbol = 'MAPPROPERTY_' + name
        if symbol in seen_prop_symbols or str(value) in properties:
            raise ValueError('Duplicate MAPPROPERTY entry')
        seen_prop_symbols.add(symbol)
        properties[str(value)] = dict(id=value, symbol=symbol)
    if not maptypes or not properties:
        raise ValueError('PACKET_ZC_MAPPROPERTY enums were not found')
    return dict(maptypes=maptypes, maptype_last=maptype_last, properties=properties,
                property_last=property_last, samples=samples)


def build_zc_symbols(path) -> dict:
    path = Path(path)
    data = path.read_bytes()
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ValueError('PACKET_ZC_MAPPROPERTY source size is out of supported bounds')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('cp932')
    parsed = parse_zc_mapproperty_document(text)
    return dict(
        version=ZC_SYMBOLS_VERSION,
        kind='zc_mapproperty_symbols',
        sources=[dict(path=str(path.resolve()), sha256=_digest(data))],
        packet_id='0x02E7',
        packet_layout=dict(
            type_offset=4, table_offset=6, table_len=ZC_MAPPROPERTY_TABLE_LEN,
            note='Samples are PacketLength 33; SHOW_HP_BAR byte may be non-boolean',
        ),
        maptypes=parsed['maptypes'],
        maptype_last=parsed['maptype_last'],
        properties=parsed['properties'],
        property_last=parsed['property_last'],
        samples=parsed['samples'],
        flags_bit_layout='unconfirmed_for_099B',
        executable_mapflags=False,
    )

def load_json_catalog(path) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


_ZC_CACHE = None
_MAPTYPE_CACHE = None


def load_default_catalogs():
    global _ZC_CACHE, _MAPTYPE_CACHE
    if _ZC_CACHE is None:
        _ZC_CACHE = load_json_catalog(DEFAULT_ZC_SYMBOLS) or {}
    if _MAPTYPE_CACHE is None:
        _MAPTYPE_CACHE = load_json_catalog(DEFAULT_MAPTYPE_CATALOG) or {}
    return _ZC_CACHE, _MAPTYPE_CACHE


def reset_catalog_caches():
    global _ZC_CACHE, _MAPTYPE_CACHE
    _ZC_CACHE = None
    _MAPTYPE_CACHE = None


def decode_zc_mapproperty_table(raw: bytes, symbols: dict | None = None) -> dict:
    """Decode RECV 0x02E7 PACKET_ZC_MAPPROPERTY when length matches the known sample layout."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < ZC_MAPPROPERTY_HEADER:
        raise ValueError('ZC_MAPPROPERTY packet is truncated')
    packet_id = int.from_bytes(raw[0:2], 'little')
    length = int.from_bytes(raw[2:4], 'little')
    if packet_id != ZC_MAPPROPERTY_ID:
        raise ValueError('Unexpected packet id for ZC_MAPPROPERTY')
    if length != len(raw) or length != ZC_MAPPROPERTY_HEADER + ZC_MAPPROPERTY_TABLE_LEN:
        raise ValueError('ZC_MAPPROPERTY length does not match supported sample layout')
    type_id = int.from_bytes(raw[4:6], 'little')
    table = list(raw[6:length])
    symbols = symbols or {}
    props = symbols.get('properties') or {}
    decoded = []
    for index, value in enumerate(table):
        row = dict(index=index, value=value)
        meta = props.get(str(index))
        if meta:
            row['symbol'] = meta['symbol']
        if value:
            decoded.append(row)
    return dict(type_id=type_id, table=table, nonzero_properties=decoded)


def flags_manual_review(flags: int | None, symbols: dict | None = None) -> dict | None:
    """Memo 099B flags as hex + bit index guesses for manual confirmation."""
    if flags is None:
        return None
    if type(flags) is not int or not 0 <= flags <= 0xFFFFFFFF:
        raise ValueError('flags out of range')
    symbols = symbols or {}
    props = symbols.get('properties') or {}
    bits = [bit for bit in range(32) if flags & (1 << bit)]
    guesses = []
    for bit in bits:
        meta = props.get(str(bit))
        guesses.append(dict(
            bit=bit,
            mask=f'0x{1 << bit:08X}',
            symbol=(meta or {}).get('symbol'),
            note='bit-index guess only; 099B flags are not confirmed as mapInfoTable',
        ))
    return dict(
        raw=flags,
        hex=f'0x{flags:08X}',
        bits_set=bits,
        property_bit_guesses=guesses,
        layout_confirmed=False,
        memo=(
            f'flags={flags:#010x} bits={bits}; '
            + (
                'MAPPROPERTY symbol guesses attached for manual review'
                if guesses else 'no bits set'
            )
            + '; do not treat as executable mapflag evidence'
        ),
    )


def build_map_property_manual_review(fields: dict, map_name: str | None = None,
                                    *, zc_symbols: dict | None = None,
                                    maptype_catalog: dict | None = None) -> dict:
    """Build analysis memos for 01D6/099B (and shared type ids)."""
    if type(fields) is not dict or 'kind' not in fields:
        raise ValueError('map_property fields require kind')
    type_id = fields['kind']
    if type(type_id) is not int or type_id < 0:
        raise ValueError('kind must be a non-negative int')
    if zc_symbols is None or maptype_catalog is None:
        loaded_zc, loaded_catalog = load_default_catalogs()
        zc_symbols = zc_symbols if zc_symbols is not None else loaded_zc
        maptype_catalog = maptype_catalog if maptype_catalog is not None else loaded_catalog
    maptypes = (zc_symbols or {}).get('maptypes') or {}
    catalog_types = (maptype_catalog or {}).get('types') or {}
    type_meta = maptypes.get(str(type_id))
    in_packet = type_meta is not None
    in_catalog = str(type_id) in catalog_types
    out_of_catalog = not in_catalog
    label = None
    if in_catalog:
        label = catalog_types[str(type_id)].get('label')
    map_label = map_name or '(map_name_unresolved)'
    symbol = (type_meta or {}).get('symbol')
    memo_parts = [f'map={map_label}', f'type={type_id}']
    if symbol:
        memo_parts.append(f'symbol={symbol}')
    if label:
        memo_parts.append(f'catalog_label={label}')
    if out_of_catalog:
        memo_parts.append('OUT_OF_MAPTYPE_CATALOG — keep for manual type/mapflag confirmation')
    elif not in_packet:
        memo_parts.append('in MapTypeProperty catalog but absent from PACKET_ZC_MAPPROPERTY enum')
    else:
        memo_parts.append('type present in packet enum and MapTypeProperty catalog')
    packet_map_notes = (type_meta or {}).get('map_name_notes') or []
    review = dict(
        map_name=map_name,
        type_id=type_id,
        type_symbol=symbol,
        type_catalog_label=label,
        type_in_packet_enum=in_packet,
        type_in_maptype_catalog=in_catalog,
        out_of_catalog=out_of_catalog,
        packet_enum_map_name_notes=packet_map_notes,
        memo='; '.join(memo_parts),
        flags=flags_manual_review(fields.get('flags'), zc_symbols),
        cause_confirmed=False,
        executable_mapflags=False,
    )
    return review


def summarize_review_rows(rows: list) -> dict:
    """Compact analysis-log summary emphasizing out-of-catalog map/type pairs and flags.

    Prefer entries that already resolved map_name when the same type appears with and
    without map context (common around warp boundaries).
    """
    def better(old, new):
        if old is None:
            return True
        old_map = (old.get('manual_review') or {}).get('map_name')
        new_map = (new.get('manual_review') or {}).get('map_name')
        return old_map is None and new_map is not None

    best_out = {}
    best_known = {}
    best_flags = {}
    for row in rows:
        review = row.get('manual_review') or {}
        type_id = review.get('type_id')
        key = (review.get('map_name'), type_id)
        bucket = best_out if review.get('out_of_catalog') else best_known
        # Collapse unresolved-map and named-map separately; also keep unresolved if never named
        if key not in bucket or better(bucket.get(key), row):
            bucket[key] = row
        if review.get('map_name') is None and type_id is not None:
            named_exists = any(k[1] == type_id and k[0] for k in bucket)
            if named_exists and (None, type_id) in bucket:
                # Drop unresolved duplicate once a named row for the same type exists
                pass
        flags = review.get('flags')
        if flags:
            fkey = (review.get('map_name'), type_id, flags.get('raw'))
            if fkey not in best_flags or better(best_flags.get(fkey), row):
                best_flags[fkey] = row

    def itemize(row):
        review = row.get('manual_review') or {}
        return dict(
            map_name=review.get('map_name'),
            type_id=review.get('type_id'),
            type_symbol=review.get('type_symbol'),
            memo=review.get('memo'),
            packet_index=row.get('packet_index'),
            packet_id=row.get('packet_id'),
        )

    def prune_unresolved(bucket):
        named_types = {type_id for map_name, type_id in bucket if map_name}
        return [itemize(row) for (map_name, type_id), row in sorted(
            bucket.items(), key=lambda item: (item[0][1] is None, item[0][1] or -1, item[0][0] or ''))
            if map_name is not None or type_id not in named_types]

    out_of = prune_unresolved(best_out)
    known = prune_unresolved(best_known)
    flag_memos = []
    for (map_name, type_id, raw), row in sorted(
            best_flags.items(), key=lambda item: (item[0][1] is None, item[0][1] or -1, item[0][0] or '')):
        # Prefer named map for the same type+flags
        if map_name is None and any(
                k[1] == type_id and k[2] == raw and k[0] for k in best_flags):
            continue
        review = row.get('manual_review') or {}
        flags = review.get('flags') or {}
        flag_memos.append(dict(
            map_name=review.get('map_name'),
            type_id=review.get('type_id'),
            flags_hex=flags.get('hex'),
            bits_set=flags.get('bits_set'),
            property_bit_guesses=flags.get('property_bit_guesses'),
            memo=flags.get('memo'),
            packet_index=row.get('packet_index'),
        ))
    return dict(
        kind='map_property_manual_review_log',
        out_of_catalog_count=len(out_of),
        known_type_count=len(known),
        out_of_catalog=out_of,
        known_types=known,
        flag_memos=flag_memos,
        note='Out-of-catalog rows and flag bit guesses are for manual confirmation only',
    )
