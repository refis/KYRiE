"""Validated values shared by dialogue and manually adopted timer templates."""
import json


def template_values(fields):
    if not isinstance(fields.get('text'), str) or len(fields['text']) > 65535:
        raise ValueError('Invalid announcement text')
    text = json.dumps(fields['text'], ensure_ascii=False)
    if set(fields) == {'text', 'broadcast_prefix'}:
        prefix = fields['broadcast_prefix']
        if prefix not in (None, 'blue', 'ssss', 'tool'):
            raise ValueError('Invalid broadcast prefix')
        return 'announcement', dict(text=text, flag={None: 0, 'blue': 16, 'ssss': 32, 'tool': 48}[prefix])
    keys = ('color', 'font_type', 'font_size', 'font_align', 'font_y')
    if set(fields) != {'text', *keys} or any(type(fields[key]) is not int or
            not 0 <= fields[key] <= (0xffffffff if key == 'color' else 65535) for key in keys):
        raise ValueError('Invalid announcement style')
    return 'announcement_styled', dict(fields, text=text)
