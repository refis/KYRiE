"""Auriga npcwalkwait timing from observed distance and NPC speed.

Matches auriga/src/map/buildin_npc.c buildin_npcwalkwait + path_distance:
Chebyshev distance; cardinal cells cost speed, diagonal cells cost speed*14/10;
optional extra ms is clamped to at least 50 (Auriga default when omitted).
"""


def chebyshev_distance(x0, y0, x1, y1):
    return max(abs(x0 - x1), abs(y0 - y1))


def npc_walk_wait_ms(x, y, destination_x, destination_y, speed, *, extra_ms=50):
    """Total script pause ms that npcwalkwait would schedule (walk + extra)."""
    if not all(type(value) is int for value in (x, y, destination_x, destination_y, speed, extra_ms)):
        raise ValueError('npcwalkwaitの座標・速度・追加msは整数である必要があります。')
    if not 0 <= speed <= 65535:
        raise ValueError('NPC speedが範囲外です。')
    delay = 50 if extra_ms < 50 else extra_ms
    dx = abs(x - destination_x)
    dy = abs(y - destination_y)
    dist = dx if dx > dy else dy
    if x == destination_x or y == destination_y:
        return speed * dist + delay
    # Approximate orthogonal/diagonal split of a Chebyshev path.
    diagonal = dx if dx < dy else dy
    cardinal = abs(dx - dy)
    return speed * cardinal + speed * diagonal * 14 // 10 + delay
