"""All observed NPC placements with optional dialogue merging; no missing-data inference."""
from reconstruction.touch import is_touch, merge_contexts, compare_conversation_trials, format_trial_comparison
from reconstruction.actor_identity import actor_sort_key
from reconstruction.actor_appearance import player_class
from reconstruction.instance_names import projection as instance_projection
from dataclasses import asdict
from copy import deepcopy
import json
from collections import Counter

from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged, conversation_path
from reconstruction.entity_metadata import render_npc_initialization
from reconstruction.npc_initial_state import visibility_state
from reconstruction.shop_export import ShopRenderer, shop_name_for
from reconstruction.barter_export import BarterRenderer, barter_name_for


def build_npc_bundle(entities, conversations, source_sessions=None, *, merge=False, shops=(),
                     barters=(), max_chars=64 * 1024 * 1024, identity=None, touch_inferences=None,
                     client_names=None, indent=None):
    conversations = list(conversations)
    sources = dict(source_sessions or {})
    renderer = AurigaRenderer(identity=identity, indent=indent)
    buckets, excluded = {}, []
    def source(item):
        return str(sources.get(item.capture_session, sources.get(str(item.capture_session), '')))
    def add(npc, reference):
        npc = dict(npc)
        if type(npc.get('actor_id')) is not int and type(reference.get('actor_id')) is int:
            npc['actor_id'] = reference['actor_id']
        try:
            key = tuple(sorted(renderer.placement_values(npc, actor_id=reference.get('actor_id')).items()))
        except ValueError as exc:
            excluded.append(dict(reference, reason=str(exc), npc=deepcopy(npc)))
            return None
        if key not in buckets:
            buckets[key] = dict(npc=deepcopy(npc), entities=[], conversations=[], metadata=[])
        order = actor_sort_key(dict(npc, actor_id=reference.get('actor_id', npc.get('actor_id')),
                                   capture_session=reference.get('capture_session', npc.get('capture_session', 0))))
        buckets[key]['sort_key'] = min(buckets[key].get('sort_key', order), order)
        buckets[key]['metadata'].append(deepcopy(npc))
        return buckets[key]
    for npc in entities:
        if npc.get('kind') != 'NPC':
            continue
        bucket = add(npc, dict(kind='entity', capture_session=npc['capture_session'], actor_id=npc['actor_id'],
                               appearance=npc['appearance']))
        if bucket is not None:
            bucket['entities'].append(deepcopy(npc))
    for item in conversations:
        bucket = add(item.npc, dict(kind='conversation', capture_session=item.capture_session, conversation_id=item.id, actor_id=item.actor_id))
        if bucket is not None:
            bucket['conversations'].append(deepcopy(item))
        else:
            excluded[-1]['conversation'] = asdict(item)
    shop_renderer = ShopRenderer(client_names=client_names) if shops else None
    lookup = {(item.capture_session, item.id): item for item in conversations}
    for record in shops:
        record = deepcopy(record)
        linked = lookup.get((record['capture_session'], record.get('conversation_id')))
        dialogue = linked is not None and any(step['kind'] not in ('open', 'dismiss') for step in linked.steps)
        mode = 'callshop' if dialogue else 'shop'
        try:
            definition = shop_renderer.render(record, mode, conversation=linked, review_unconfirmed=True)
        except (ValueError, OSError) as exc:
            excluded.append(dict(kind='shop', record=record, reason=str(exc)))
            continue
        npc = linked.npc if dialogue else record['npc']
        bucket = add(npc, dict(kind='shop', record=record, actor_id=record.get('actor_id'), capture_session=record['capture_session']))
        if bucket is None:
            continue
        entry = dict(record=record, mode=mode, item_ids_confirmed=False)
        if dialogue:
            name = shop_name_for(npc, record['items'])
            products = ','.join(f'{item["client_item_id"]}:{item["price"]}' for item in record['items'])
            entry.update(name=name, definition=shop_renderer.templates['hidden_shop'].format(shop_name=name, items=products))
            for item in bucket['conversations']:
                if (item.capture_session, item.id) == (linked.capture_session, linked.id):
                    previous = item.termination.get('shop_call_name')
                    if previous and previous != name:
                        entry['conflict'] = True
                    item.termination['shop_call_name'] = name
        else:
            entry['definition'] = definition
        bucket.setdefault('shops', []).append(entry)
    barter_renderer = BarterRenderer() if barters else None
    for record in barters:
        record = deepcopy(record)
        linked = lookup.get((record['capture_session'], record.get('conversation_id')))
        dialogue = linked is not None and any(step['kind'] not in ('open', 'dismiss') for step in linked.steps)
        if not dialogue:
            excluded.append(dict(kind='barter', record=record, reason='本文を伴う対応会話が必要です。'))
            continue
        try:
            name, definition = barter_renderer.hidden_definition(record, linked.npc)
            # Validate linkage the same way as individual export.
            barter_renderer.render(record, conversation=linked, review_unconfirmed=True)
        except (ValueError, OSError) as exc:
            excluded.append(dict(kind='barter', record=record, reason=str(exc)))
            continue
        bucket = add(linked.npc, dict(kind='barter', record=record, actor_id=record.get('actor_id'),
                                      capture_session=record['capture_session']))
        if bucket is None:
            continue
        entry = dict(record=record, mode='callbarter', item_ids_confirmed=False, name=name, definition=definition)
        for item in bucket['conversations']:
            if (item.capture_session, item.id) == (linked.capture_session, linked.id):
                previous = item.termination.get('barter_call_name')
                if previous and previous != name:
                    entry['conflict'] = True
                item.termination['barter_call_name'] = name
        bucket.setdefault('barters', []).append(entry)
    entries, size = [], 0
    for _, bucket in sorted(buckets.items(), key=lambda item: (item[1]['sort_key'], item[0])):
        shop_entries = bucket.get('shops', [])
        barter_entries = bucket.get('barters', [])
        direct_keys = {(row['record']['capture_session'], row['record'].get('conversation_id'))
                       for row in shop_entries if row['mode'] == 'shop'}
        items = [item for item in bucket['conversations'] if (item.capture_session, item.id) not in direct_keys]
        bodies, used = [], set()
        merge_exclusions = []
        touch_trial_comparison = []
        touch_trial_caption = ''
        if merge and items:
            combined = build_merged(((source(item), item) for item in items),
                                    touch_inferences=touch_inferences)
            merge_exclusions = combined['excluded']
            for group in combined['groups']:
                if group.get('touch_trial_comparison') and not touch_trial_comparison:
                    touch_trial_comparison = group['touch_trial_comparison']
                    touch_trial_caption = group.get('touch_trial_caption') or format_trial_comparison(touch_trial_comparison)
                try:
                    bodies.append(renderer.render_merged(group, include_initialization=False))
                except ValueError as exc:
                    excluded.append(dict(kind='merged_conversation', group_id=group['id'], reason=str(exc)))
                    continue
                used.update((row['source_ref'], row['capture_session'], row['conversation_id']) for row in group['contributions'])
        elif items and any(is_touch(item.npc) for item in items):
            touch_trial_comparison = compare_conversation_trials(
                items, touch_inferences, source_refs=sources)
            touch_trial_caption = format_trial_comparison(touch_trial_comparison)
        for item in items:
            if (source(item), item.capture_session, item.id) in used:
                continue
            try:
                bodies.append(renderer.render(item, include_initialization=False))
            except ValueError as exc:
                excluded.append(dict(kind='conversation', capture_session=item.capture_session,
                                     conversation_id=item.id, reason=str(exc)))
        if not bodies:
            body = renderer.templates['npc_unobserved_body'] + '\n' + renderer.templates['end']
        elif len(bodies) == 1:
            body = bodies[0].rstrip()
        else:
            lines = [renderer.templates['alternatives']]
            for number, text in enumerate(bodies, 1):
                lines.extend([renderer.templates['alternative'].format(number=number),
                              renderer.templates['block_open'].format_map({})])
                lines.extend(renderer.templates['indent'] + line for line in text.rstrip().splitlines())
                lines.append(renderer.templates['block_close'].format_map({}))
            body = '\n'.join(lines)
        if not bodies:
            body = ''
        initialization = render_npc_initialization(bucket['metadata'], indent=renderer.templates['indent'])
        if initialization:
            if not body:
                body = renderer.templates['end']
            body += '\n\n' + initialization.rstrip()
        npc = deepcopy(bucket['npc'])
        touches = [row['touch'] for row in bucket['metadata'] if is_touch(row)]
        if touches:
            npc['touch'] = merge_contexts(touches)
        if (touches and items and not initialization and not shop_entries and not barter_entries
                and all(not item.actions and not item.resource_observations and not item.parallel_presentations
                        and not item.external_presentations for item in items)):
            paths = [conversation_path('', item, strict=False) for item in items]
            if all(path and all(token['kind'] in ('post_close_warp', 'end') for token in path)
                   and sum(token['kind'] == 'post_close_warp' for token in path) == 1 for path in paths):
                targets = [next(token['fields'] for token in path if token['kind'] == 'post_close_warp') for path in paths]
                if all(target == targets[0] for target in targets):
                    npc['warp_target'] = deepcopy(targets[0])
        try:
            states = {visibility_state(item) for item in bucket['metadata']} - {'unobserved'}
            observed = next((item for item in bucket['metadata'] if item.get('initial_options') is not None), None)
            if observed:
                npc.update(initial_options=observed['initial_options'],
                           initial_state_evidence=deepcopy(observed.get('initial_state_evidence', {})),
                           actor_type=observed.get('actor_type', npc.get('actor_type')))
            direct = list(dict.fromkeys(row['definition'].rstrip() for row in shop_entries if row['mode'] == 'shop'))
            hidden = list(dict.fromkeys(row['definition'].rstrip() for row in shop_entries if row['mode'] == 'callshop'))
            commented_barters = list(dict.fromkeys(row['definition'].rstrip() for row in barter_entries))
            if direct and not bodies:
                code = '\n\n'.join(direct) + '\n'
                if initialization:
                    code += '\n' + '\n'.join('// ' + line for line in initialization.splitlines()) + '\n'
            else:
                code = renderer._wrap_npc(npc, body)
                if direct:
                    code += '\n' + '\n\n'.join(direct) + '\n'
            preface = []
            if hidden:
                preface.append(renderer.templates['npc_shop_ids_review'] + '\n' + '\n\n'.join(hidden))
            if commented_barters:
                preface.append('\n\n'.join(commented_barters))
            if preface:
                code = '\n\n'.join(preface) + '\n\n' + code
        except ValueError as exc:
            excluded.append(dict(kind='npc_initial_state', reason=str(exc), npc=npc,
                observations=bucket['metadata'], entities=bucket['entities'], shops=shop_entries,
                barters=barter_entries, conversations=[asdict(item) for item in items]))
            continue
        size += len(code)
        if size > max_chars:
            raise ValueError('NPC一括出力が上限を超えています。')
        entries.append(dict(npc=npc, rendered_names=instance_projection(npc), entities=bucket['entities'],
            conversations=[asdict(item) for item in bucket['conversations']], shops=shop_entries,
            barters=barter_entries, dialogue_mode='merged' if merge else 'individual',
            rendered_paths=len(bodies), auriga=code,
            touch_trial_comparison=touch_trial_comparison,
            touch_trial_caption=touch_trial_caption,
            review_only=any(row['mode'] == 'shop' and (visibility_state(row['record']['npc'])
                            in ('hidden', 'cloaked', 'ambiguous') or player_class((row['record']['npc'].get('initial_display') or {}).get('class_id',row['record']['npc'].get('class_id')))) for row in shop_entries)
                or bool(barter_entries),
            initial_state_conflict=len(states) > 1,
            shop_conflict=len(direct) > 1 or len(hidden) > 1 or bool(direct and bodies)
                or any(row.get('conflict') for row in shop_entries)
                or any(row.get('conflict') for row in barter_entries)))
        entries[-1]['merge_exclusions'] = merge_exclusions
    names = Counter(entry['npc']['name'] for entry in entries)
    texts = []
    for entry in entries:
        code = entry['auriga']
        if entry['initial_state_conflict'] or entry['shop_conflict']:
            entry['review_only'] = True
            warning = (renderer.templates['npc_shop_conflict'] if entry['shop_conflict']
                       else renderer.templates['npc_initial_state_conflict'])
            code = warning + '\n' + '\n'.join('// ' + line for line in code.splitlines()) + '\n'
        elif names[entry['npc']['name']] > 1:
            # Same display name at different placements is allowed; keep a warning only.
            warning = renderer.templates['npc_name_conflict'].format(
                name=json.dumps(entry['npc']['name'], ensure_ascii=False))
            code = warning + '\n' + code
        entry['auriga'] = code
        texts.append(code)
    header = renderer.templates['npc_bundle_header'].format(count=len(entries), excluded=len(excluded),
                                                           mode='統合' if merge else '個別')
    text = header + '\n\n' + '\n\n'.join(text.rstrip() for text in texts) + '\n'
    if excluded:
        text += '\n// ' + json.dumps(dict(excluded=excluded), ensure_ascii=True) + '\n'
    if len(text) > max_chars:
        raise ValueError('NPC一括出力が上限を超えています。')
    return dict(schema_version=1, kind='npc_bundle', dialogue_merged=merge, source_sessions=sources,
                entries=entries, excluded=excluded, auriga=text,
                review_only_count=sum(entry['review_only'] for entry in entries))
