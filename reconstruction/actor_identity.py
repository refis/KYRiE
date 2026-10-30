"""Server ActorID namespaces, separate from visibility intervals and spawn settings."""
import ast
import ipaddress


def server_endpoint(packet):
    text = packet.connection.split(' [', 1)[0]
    if len(text) > 512:
        return None
    try:
        endpoints = ast.literal_eval(text)
        if not isinstance(endpoints, tuple) or len(endpoints) != 4:
            return None
        offset = 0 if packet.direction == 'RECV' else 2
        address, port = endpoints[offset:offset + 2]
        if not isinstance(address, str) or type(port) is not int or not 1 <= port <= 65535:
            return None
        return dict(ip=str(ipaddress.ip_address(address)), port=port)
    except (ValueError, SyntaxError, TypeError, RecursionError):
        return None


def server_actor_observations(entities):
    buckets, unknown = {}, 0
    for entity in entities:
        server = entity.server_endpoint
        if server is None:
            unknown += 1
            continue
        key = (entity.capture_session, server['ip'], server['port'], entity.actor_id)
        bucket = buckets.setdefault(key, dict(capture_session=entity.capture_session,
            server_endpoint=dict(server), actor_id=entity.actor_id, observation_keys=[],
            instance_mode=False, same_entity_confirmed=False))
        bucket['observation_keys'].append(list(entity.key))
        bucket['instance_mode'] |= '@' in (entity.map_name or '')
    for bucket in buckets.values():
        bucket['visibility_intervals'] = len(bucket['observation_keys'])
        bucket['allocation_kind'] = 'instance_runtime' if bucket['instance_mode'] else 'not_determined'
    return dict(groups=[buckets[key] for key in sorted(buckets)], unknown_server_intervals=unknown,
                cross_capture_identity_confirmed=False, script_spawn_count_inferred=False)


def actor_sort_key(entity):
    """Server address/port, numeric ActorID, then stable observation ties."""
    def get(name, default=None):
        return entity.get(name, default) if isinstance(entity, dict) else getattr(entity, name, default)
    server = get('server_endpoint')
    try:
        address = ipaddress.ip_address(server['ip'])
        port = server['port']
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid server port')
        namespace = (0, address.version, int(address), port, '')
    except (TypeError, KeyError, ValueError):
        namespace = (1, 0, 0, 0, str(get('connection', '')))
    actor = get('actor_id')
    actor = actor if type(actor) is int and actor >= 0 else 0x100000000
    return (*namespace, actor, get('capture_session', 0) or 0,
            get('map_generation', 0) or 0, get('appearance', 0) or 0,
            str(get('map_name', '')), str(get('name', '')))
