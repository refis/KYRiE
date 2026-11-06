"""Local GUI preference profile. Not part of git, snapshots, or release artifacts."""
from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = PROJECT_ROOT / 'config' / 'user_settings.json'
MAX_BYTES = 65536
EMULATORS = frozenset({'auriga', 'rathena'})
SCRIPT_INDENTS = frozenset({'spaces', 'tabs'})
# Tab-focus presets only; never hide panels or change generation rules.
WORKSPACE_PRESETS = frozenset({'observe', 'restore'})
WORKSPACE_PRESET_CHOICES = (
    ('observe', '観測中心'),
    ('restore', '復元中心'),
)

# GUI offline replay staging budget (not live capture). CLI analyze_* has no packet cap.
DEFAULT_OFFLINE_MAX_PACKETS = 20000
DEFAULT_OFFLINE_MAX_PACKET_MIB = 32
OFFLINE_MAX_PACKETS_RANGE = (1000, 200000)
OFFLINE_MAX_PACKET_MIB_RANGE = (8, 256)

DEFAULTS = dict(
    version=1,
    capture_send=True,
    include_children=False,
    attach_existing=False,
    definitions_path=str(PROJECT_ROOT / 'PacketLength.txt'),
    overlay_path='',
    interface='',
    manual_server_ip='',
    manual_server_port='',
    emulator='auriga',
    script_indent='spaces',
    display_recv_path=str(PROJECT_ROOT / 'config' / 'auriga' / 'display.json'),
    display_send_path=str(PROJECT_ROOT / 'config' / 'send_display.json'),
    display_timestamps=False,
    display_unmapped=False,
    record_stream=False,
    log_root=str(PROJECT_ROOT / 'logs'),
    offline_max_packets=DEFAULT_OFFLINE_MAX_PACKETS,
    offline_max_packet_mib=DEFAULT_OFFLINE_MAX_PACKET_MIB,
    pipe_enabled=False,
    pipe_name='',
    merge_npc_paths=False,
    # Dismissal only; checklist never writes capture/display toggles by itself.
    startup_checklist_seen=False,
    # Initial workspace tab focus only (observe=観測ログ, restore=会話・コード).
    workspace_preset='observe',
)


def offline_replay_budget(settings=None):
    """Return (max_packets, max_packet_bytes) for GUI ReplayWorker staging."""
    document = validate(settings if settings is not None else DEFAULTS)
    return (document['offline_max_packets'],
            document['offline_max_packet_mib'] * 1024 * 1024)


def indent_value(setting):
    """Map user setting to the dialogue/entity_metadata indent string."""
    return '\t' if setting == 'tabs' else '    '


class UserSettingsError(ValueError):
    pass


def _bounded_string(value, label, maximum=4096, allow_empty=True):
    if not isinstance(value, str):
        raise UserSettingsError(f'{label}: expected string')
    if len(value) > maximum:
        raise UserSettingsError(f'{label}: too long')
    if not allow_empty and not value.strip():
        raise UserSettingsError(f'{label}: required')
    if '\0' in value:
        raise UserSettingsError(f'{label}: invalid character')
    return value


def validate(document):
    if not isinstance(document, dict) or type(document.get('version')) is not int or document['version'] != 1:
        raise UserSettingsError('Unsupported user settings version')
    allowed = set(DEFAULTS)
    if set(document) - allowed:
        raise UserSettingsError('Unknown user settings keys')
    result = deepcopy(DEFAULTS)
    for key, default in DEFAULTS.items():
        if key not in document:
            continue
        value = document[key]
        if key == 'version':
            continue
        if type(default) is bool:
            if type(value) is not bool:
                raise UserSettingsError(f'{key}: expected boolean')
            result[key] = value
        elif key == 'offline_max_packets':
            if type(value) is not int or isinstance(value, bool):
                raise UserSettingsError(f'{key}: expected integer')
            low, high = OFFLINE_MAX_PACKETS_RANGE
            if not low <= value <= high:
                raise UserSettingsError(f'{key}: must be {low}..{high}')
            result[key] = value
        elif key == 'offline_max_packet_mib':
            if type(value) is not int or isinstance(value, bool):
                raise UserSettingsError(f'{key}: expected integer')
            low, high = OFFLINE_MAX_PACKET_MIB_RANGE
            if not low <= value <= high:
                raise UserSettingsError(f'{key}: must be {low}..{high}')
            result[key] = value
        elif key == 'emulator':
            if value not in EMULATORS:
                raise UserSettingsError('emulator must be auriga or rathena')
            result[key] = value
        elif key == 'script_indent':
            if value not in SCRIPT_INDENTS:
                raise UserSettingsError('script_indent must be spaces or tabs')
            result[key] = value
        elif key == 'workspace_preset':
            if value not in WORKSPACE_PRESETS:
                raise UserSettingsError('workspace_preset must be observe or restore')
            result[key] = value
        elif key == 'manual_server_port':
            text = _bounded_string(value, key, 16)
            if text.strip() and not re.fullmatch(r'[1-9][0-9]{0,4}', text.strip()):
                raise UserSettingsError('manual_server_port: invalid TCP port')
            if text.strip() and not 1 <= int(text.strip()) <= 65535:
                raise UserSettingsError('manual_server_port: out of range')
            result[key] = text.strip()
        elif key == 'pipe_name':
            text = _bounded_string(value, key, 128)
            if text and not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', text):
                raise UserSettingsError('pipe_name: invalid characters')
            result[key] = text
        else:
            result[key] = _bounded_string(value, key)
    return result


def load(path=None):
    path = Path(DEFAULT_PATH if path is None else path)
    if not path.is_file():
        return deepcopy(DEFAULTS)
    if path.stat().st_size > MAX_BYTES:
        raise UserSettingsError('User settings exceed size limit')
    try:
        document = json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UserSettingsError(f'Invalid user settings JSON: {exc}') from exc
    return validate(document)


def save(document, path=None):
    path = Path(DEFAULT_PATH if path is None else path)
    payload = validate(document)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise UserSettingsError('User settings exceed size limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix=path.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return payload


def collect_from_window(window):
    """Read current GUI controls into a settings document."""
    emulator = window.emulator.currentData()
    if emulator not in EMULATORS:
        emulator = 'auriga'
    script_indent = window.script_indent.currentData() if hasattr(window, 'script_indent') else 'spaces'
    if script_indent not in SCRIPT_INDENTS:
        script_indent = 'spaces'
    direction = getattr(window, 'selected_display_direction', 'RECV')
    recv_path = window.display_input_paths.get('recv', '')
    send_path = window.display_input_paths.get('SEND', '')
    if direction == 'RECV':
        recv_path = window.display_path.text().strip() or recv_path
    else:
        send_path = window.display_path.text().strip() or send_path
    return validate(dict(
        version=1,
        capture_send=window.capture_send.isChecked(),
        include_children=window.children.isChecked(),
        attach_existing=window.attach_existing.isChecked(),
        definitions_path=window.path.text().strip(),
        overlay_path=window.overlay_path.text().strip(),
        interface=window.iface.text().strip(),
        manual_server_ip=window.ip.text().strip(),
        manual_server_port=window.port.text().strip(),
        emulator=emulator,
        script_indent=script_indent,
        display_recv_path=recv_path,
        display_send_path=send_path,
        display_timestamps=window.display_timestamps.isChecked(),
        display_unmapped=window.display_unmapped.isChecked(),
        record_stream=window.record_stream.isChecked(),
        log_root=window.log_root.text().strip(),
        offline_max_packets=int(window.offline_max_packets.value()),
        offline_max_packet_mib=int(window.offline_max_packet_mib.value()),
        pipe_enabled=window.pipe_enabled.isChecked(),
        pipe_name=window.pipe_name.text().strip(),
        merge_npc_paths=window.dialogue_panel.merge_checkbox.isChecked(),
        startup_checklist_seen=bool(getattr(window, 'startup_checklist_seen', False)),
        workspace_preset=_workspace_preset_from_window(window),
    ))


def _workspace_preset_from_window(window):
    combo = getattr(window, 'workspace_preset', None)
    if combo is not None and hasattr(combo, 'currentData'):
        value = combo.currentData()
        if value in WORKSPACE_PRESETS:
            return value
    value = getattr(window, 'workspace_preset_value', None)
    return value if value in WORKSPACE_PRESETS else 'observe'


def apply_to_window(window, settings):
    """Apply a validated settings document to GUI controls without firing side effects."""
    document = validate(settings)
    controls = [
        window.capture_send, window.children, window.attach_existing, window.emulator,
        window.display_timestamps, window.display_unmapped, window.record_stream,
        window.pipe_enabled, window.dialogue_panel.merge_checkbox,
    ]
    if hasattr(window, 'script_indent'):
        controls.append(window.script_indent)
    for control in controls:
        control.blockSignals(True)
    try:
        window.capture_send.setChecked(document['capture_send'])
        window.children.setChecked(document['include_children'])
        window.attach_existing.setChecked(document['attach_existing'])
        window.path.setText(document['definitions_path'])
        window.overlay_path.setText(document['overlay_path'])
        window.iface.setText(document['interface'])
        window.ip.setText(document['manual_server_ip'])
        window.port.setText(document['manual_server_port'])
        emulator_index = window.emulator.findData(document['emulator'])
        if emulator_index < 0:
            emulator_index = 0
        window.emulator.setCurrentIndex(emulator_index)
        window.last_emulator_index = emulator_index
        if hasattr(window, 'script_indent'):
            indent_index = window.script_indent.findData(document['script_indent'])
            if indent_index < 0:
                indent_index = 0
            window.script_indent.setCurrentIndex(indent_index)
        window.display_input_paths['recv'] = document['display_recv_path']
        window.display_input_paths['SEND'] = document['display_send_path']
        window.display_profile_paths['recv'] = document['display_recv_path']
        window.display_profile_paths['SEND'] = document['display_send_path']
        direction = getattr(window, 'selected_display_direction', 'RECV')
        active = document['display_recv_path'] if direction == 'RECV' else document['display_send_path']
        window.display_path.setText(active)
        window.display_timestamps.setChecked(document['display_timestamps'])
        window.display_unmapped.setChecked(document['display_unmapped'])
        window.render_timestamps = document['display_timestamps']
        window.record_stream.setChecked(document['record_stream'])
        window.log_root.setText(document['log_root'])
        window.offline_max_packets.blockSignals(True)
        window.offline_max_packet_mib.blockSignals(True)
        window.offline_max_packets.setValue(document['offline_max_packets'])
        window.offline_max_packet_mib.setValue(document['offline_max_packet_mib'])
        window.offline_max_packets.blockSignals(False)
        window.offline_max_packet_mib.blockSignals(False)
        window.pipe_enabled.setChecked(document['pipe_enabled'])
        if document['pipe_name']:
            window.pipe_name.setText(document['pipe_name'])
        window.dialogue_panel.merge_checkbox.setChecked(document['merge_npc_paths'])
        if hasattr(window, 'export_merge_action'):
            window.export_merge_action.blockSignals(True)
            window.export_merge_action.setChecked(document['merge_npc_paths'])
            window.export_merge_action.blockSignals(False)
        window.startup_checklist_seen = document['startup_checklist_seen']
        window.workspace_preset_value = document['workspace_preset']
        combo = getattr(window, 'workspace_preset', None)
        if combo is not None and hasattr(combo, 'findData'):
            combo.blockSignals(True)
            index = combo.findData(document['workspace_preset'])
            if index < 0:
                index = 0
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
        apply_workspace_preset(window, document['workspace_preset'])
    finally:
        for control in controls:
            control.blockSignals(False)
    return document


def apply_workspace_preset(window, preset=None):
    """Focus the preset's primary tab. All tabs remain available."""
    value = preset if preset in WORKSPACE_PRESETS else getattr(window, 'workspace_preset_value', 'observe')
    if value not in WORKSPACE_PRESETS:
        value = 'observe'
    window.workspace_preset_value = value
    tabs = getattr(window, 'workspace_tabs', None)
    if tabs is None:
        return value
    if value == 'restore' and getattr(window, 'dialogue_panel', None) is not None:
        tabs.setCurrentWidget(window.dialogue_panel)
    else:
        tabs.setCurrentIndex(0)
    return value
