"""In-memory packet retention bound. Durable evidence stays in SQLite/session log."""

# Soft default keeps common GUI tests under the cap; override in tests for eviction.
MEMORY_EVENT_LIMIT = 50000


def physical_index(logical, origin):
    if type(logical) is not int or type(origin) is not int or origin < 0:
        raise ValueError('Invalid history index')
    return logical - origin


def trim_parallel(lists, count):
    """Drop the oldest `count` entries from each parallel list in place."""
    if type(count) is not int or count < 0:
        raise ValueError('Invalid trim count')
    if count == 0:
        return
    for rows in lists:
        if count > len(rows):
            raise ValueError('Trim exceeds retained history')
        del rows[:count]
