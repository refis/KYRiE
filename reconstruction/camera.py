"""Observed camera values and exact Auriga integer-argument conversion."""
import math
import struct


def auriga_arguments(fields):
    if fields['show'] != 0:
        return None
    result = {}
    for key in ('range', 'rotation', 'latitude'):
        value = fields[key]
        if not math.isfinite(value):
            return None
        argument = round(value * 100)
        if not -2147483648 <= argument <= 2147483647:
            return None
        # C converts the integer to float before dividing by 100.0f.
        as_float = struct.unpack('<f', struct.pack('<f', argument))[0]
        reproduced = struct.pack('<f', as_float / 100.0)
        if reproduced != struct.pack('<f', value):
            return None
        result[key] = argument
    return result
