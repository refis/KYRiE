"""Evidence-based script command candidates; uncertain arguments stay review-only."""
from collections import OrderedDict, deque
from copy import deepcopy
import json
from pathlib import Path

from reconstruction.decoder import Reader, ObservationError
from reconstruction.player import decode_player, LIST_STRIDES
from reconstruction.instance_names import map_name

POLICY_PATH = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'script_commands.json'
COMMAND_ARGS = {
    'openstorage': (), 'getitem': ('item_id', 'amount'),
    'getitem2': ('item_id', 'amount', 'identified', 'refine', 'attribute', 'card1', 'card2', 'card3', 'card4'),
    'delitem': ('item_id', 'amount'), 'delequip': ('slot',), 'unequip': ('slot',),
    'successrefitem': ('slot',), 'failedrefitem': ('slot',), 'downrefitem': ('slot', 'decrement'),
    'sit': (), 'stand': (), 'dropitem': ('map_name', 'x', 'y', 'item_id', 'amount', 'extra_lifetime_ms')}


def load_policy(path=None):
    from reconstruction.emulator_profiles import profile
    path = Path(path) if path is not None else profile('script_commands.json')
    if path.stat().st_size > 65536:
        raise ValueError('Script command policy exceeds 64KiB')
    result = json.loads(path.read_text(encoding='utf-8'))
    if result.get('version') != 1 or type(result.get('correlation_ms')) is not int or not 0 < result['correlation_ms'] <= 10000:
        raise ValueError('Invalid command correlation policy')
    for key in ('dropitem_lifetime_ms','flooritem_base_lifetime_ms'):
        lifetime = result.get(key)
        if lifetime is not None and (type(lifetime) is not int or not 0 <= lifetime <= 2147483647):
            raise ValueError('Invalid manual drop lifetime')
    if result.get('dropitem_lifetime_ms') == 0:
        raise ValueError('Drop lifetime must be positive')
    if not isinstance(result.get('equip_slots'), dict) or any(not k.isdecimal() or type(v) is not int or not 1 <= v <= 22 for k,v in result['equip_slots'].items()):
        raise ValueError('Invalid equipment slot map')
    requests = result.get('request_ids')
    required = {'unequip', 'posture', 'drop', 'walk', 'cart_from_body', 'cart_to_body'}
    if not isinstance(requests, dict) or set(requests) != required:
        raise ValueError('Invalid request packet groups')
    for key, values in requests.items():
        if not isinstance(values, list) or len(values) > 64:
            raise ValueError('Invalid request packet group')
        try:
            requests[key] = frozenset(int(value, 16) for value in values)
        except (ValueError, TypeError):
            raise ValueError('Invalid request PacketID') from None
        if any(not 0 <= value <= 65535 for value in requests[key]):
            raise ValueError('Invalid request PacketID range')
    return result


def render_command(fields, style):
    command, args = fields['command'], fields['arguments']
    if command not in COMMAND_ARGS or set(args) != set(COMMAND_ARGS[command]):
        raise ValueError('Invalid script command arguments')
    values = {}
    missing = False
    for name, value in args.items():
        if value is None:
            missing = True
            values[name] = '__' + name.upper() + '__'
        elif name == 'map_name':
            if not isinstance(value, str) or not value:
                raise ValueError('Unknown drop map')
            reference = json.dumps(map_name(value), ensure_ascii=False)
            values[name] = style['instance_map_reference'].format(name=reference) if '@' in value else reference
        elif name == 'extra_lifetime_ms' and type(value) is int and -2147483648 <= value <= 2147483647:
            values[name] = value
        elif type(value) is not int or not 0 <= value <= 0xffffffff:
            raise ValueError('Invalid script command value')
        else:
            if value > 2147483647:
                missing = True
            values[name] = value
    code = style['script_' + command].format_map(values)
    if missing or fields.get('review_only'):
        code = style['script_review'].format(code=code, reason=fields.get('reason') or '引数が未観測またはスクリプト数値範囲外')
    if command == 'dropitem' and fields.get('lifetime_ms') is not None and fields.get('base_lifetime_ms') is not None:
        code = style['script_drop_lifetime_note'].format(lifetime_ms=fields['lifetime_ms'],base_ms=fields['base_lifetime_ms']) + '\n' + code
    return code


class ScriptCommandStore:
    def __init__(self, policy=None):
        self.policy = load_policy() if policy is None else deepcopy(policy)
        self.states = OrderedDict()
        self.observations = []
        self.links = {}
        self.dropped = 0
        self.capture = -1

    def _state(self, key):
        if key not in self.states:
            if len(self.states) >= 64:
                self.states.popitem(last=False)
            self.states[key] = dict(inventory={}, pending={}, recent=deque(maxlen=64), generation=None,
                                    floor=set(), settled=False, storage=False, death=None, pending_incomplete=False,
                                    cart_to_body=deque(maxlen=64))
        return self.states[key]

    def link(self, record, action):
        if action is not None:
            self.links[record['packet_index'], record['capture_session']] = action

    def _suppress(self, record, reason):
        record['fields'].update(review_only=True, reason=reason)
        linked = self.links.get((record['packet_index'], record['capture_session']))
        if linked:
            linked['fields'].update(review_only=True, reason=reason)

    def observe(self, packet, session, index, world, conversation, values=None):
        if session > self.capture:
            self.capture = session
            self.states.clear()
        if session < self.capture:
            return []
        key = (session, packet.flow_id or packet.connection)
        state = self._state(key)
        scene = world.scenes.get((session, packet.connection)) if world else None
        generation = scene.generation if scene else state['generation']
        if generation != state['generation']:
            state.update(generation=generation, pending={}, floor=set(), settled=False, storage=False, death=None,
                         pending_incomplete=False, cart_to_body=deque(maxlen=64))
            state['recent'].clear()
        r, pid = Reader(packet.raw), packet.packet_id
        out = []
        def nearby(stamp):
            return stamp is not None and 0 <= (packet.timestamp - stamp) * 1000 <= self.policy['correlation_ms']
        def emit(command, arguments, *, review=False, reason='', slot_index=None, observed=None):
            if len(self.observations) >= 10000:
                self.dropped += 1
                raise ObservationError('Script command observation capacity reached')
            record = dict(capture_session=session, flow_id=key[1], map_generation=generation,
                conversation_id=conversation.id if conversation else None, after_step_index=len(conversation.steps)-1 if conversation else None,
                packet_index=index, packet_id=pid, timestamp=packet.timestamp, direction=packet.direction,
                connection=packet.connection, source=packet.source, cause_confirmed=False, slot_index=slot_index,
                observed=deepcopy(observed or {}), fields=dict(command=command, arguments=arguments, review_only=review, reason=reason))
            self.observations.append(record); state['recent'].append(record); out.append(record)
            return record
        if packet.direction == 'SEND':
            if pid in (0x72,0x436):
                state.update(inventory={}, pending={}, pending_incomplete=False, cart_to_body=deque(maxlen=64))
            if len(state['pending']) >= 256 or len(state['cart_to_body']) >= 64:
                state['pending_incomplete'] = True
                raise ObservationError('Command request correlation capacity reached')
            requests = self.policy['request_ids']
            if pid in requests['unequip']:
                state['pending']['unequip', r.number(2, 'H')] = packet.timestamp
            elif pid in requests['posture']:
                state['pending']['posture', r.number(6, 'B')] = packet.timestamp
            elif pid in requests['drop']:
                state['pending']['drop'] = packet.timestamp
                state['pending']['drop',r.number(2,'H')] = packet.timestamp
            elif pid in requests['cart_from_body']:
                if len(packet.raw) != 8:
                    raise ObservationError('Unsupported cart move-from-body layout')
                # Body index and amount; cart index is a different namespace.
                state['pending']['cart_from_body', r.number(2, 'H'), r.number(4, 'I')] = dict(
                    timestamp=packet.timestamp, packet_index=index)
            elif pid in requests['cart_to_body']:
                if len(packet.raw) != 8:
                    raise ObservationError('Unsupported cart move-to-body layout')
                # Cart index is not the inventory index of the eventual gain.
                state['cart_to_body'].append(dict(cart_index=r.number(2, 'H'), amount=r.number(4, 'I'),
                                                  timestamp=packet.timestamp, packet_index=index))
            elif pid in requests['walk'] or pid == 0x90:
                state['settled'] = True
            return out
        if pid == 0x87:
            state['settled'] = True
        if pid == 0x80 and len(packet.raw) == 7 and r.number(6, 'B') == 1 and world:
            actor = r.number(2, 'I')
            if any(e.actor_id == actor and e.capture_session == session and e.flow_id == key[1]
                   and e.kind == 'MOB' and e.map_generation == generation for e in world.records('MOB')):
                state['death'] = packet.timestamp
                for old in state['recent']:
                    if old['fields']['command']=='dropitem' and nearby(old['timestamp']):
                        self._suppress(old,'後続のMOB死亡通知と相関するためdropitem候補を除外')
        if pid == 0xb08 and len(packet.raw)>=5 and r.number(4,'B')==0:
            state['inventory'].clear()
        if values and values.get('observation_error') and pid in (*LIST_STRIDES,0xa37,0xb41,0xaf,0x7fa,0xb0b):
            state['inventory'].clear()
            raise ObservationError('Player inventory observation was rejected; command metadata discarded')
        if pid == 0xf8:
            state['storage'] = False
        if pid == 0xf2:
            if len(packet.raw) != 6:
                raise ObservationError('Invalid storage amount packet')
            if not state['storage']:
                emit('openstorage', {}, observed=dict(amount=r.number(2,'H'), capacity=r.number(4,'H')))
            state['storage'] = True
        if pid in LIST_STRIDES:
            decoded = decode_player(packet)
            if decoded and decoded[0] == 'inventory_list':
                for ordinal, (inventory_index, item) in enumerate(decoded[1]['items'].items()):
                    if len(state['inventory']) >= 4096 and inventory_index not in state['inventory']:
                        raise ObservationError('Command inventory capacity reached')
                    data = dict(item)
                    if pid == 0xb0a:
                        start = 5 + ordinal * LIST_STRIDES[pid]
                        data.update(equip_mask=r.number(start+11, 'I'), last_equip_mask=r.number(start+11,'I'), refine=r.number(start+15,'B'))
                    state['inventory'][inventory_index] = data
        if pid in (0xa37, 0xb41):
            if len(packet.raw) != (69 if pid==0xa37 else 70):
                raise ObservationError('Unsupported item gain layout')
            decoded = decode_player(packet)
            fields = decoded[1]
            if fields['result'] == 0:
                inventory_index = fields['index']
                previous = state['inventory'].get(inventory_index, {})
                if previous.get('item_id') != fields['item_id'] or previous.get('amount',0) <= 0:
                    previous = {}
                if len(state['inventory']) >= 4096 and inventory_index not in state['inventory']:
                    raise ObservationError('Command inventory capacity reached')
                state['inventory'][inventory_index] = dict(previous, **fields)
                state['inventory'][inventory_index]['item_type'] = r.number(33 if pid==0xa37 else 32,'B')
                if previous.get('item_id') == fields['item_id']:
                    state['inventory'][inventory_index]['amount'] = previous.get('amount',0) + fields['amount']
                if conversation and not state['storage']:
                    cart_matches = [row for row in state['cart_to_body'] if row['amount'] == fields['amount']]
                    cart_move = None
                    if len(cart_matches) == 1:
                        cart_move = cart_matches[0]
                        state['cart_to_body'].remove(cart_move)
                    elif len(cart_matches) > 1:
                        state['pending_incomplete'] = True
                    if cart_move is not None:
                        pass  # Cart→inventory transfer is not an NPC reward.
                    elif cart_matches:
                        reason = 'カート取出し要求が複数あり報酬との対応が未確定'
                        if fields['plain_item']:
                            emit('getitem', dict(item_id=fields['item_id'], amount=fields['amount']),
                                 review=True, reason=reason, slot_index=inventory_index, observed=fields)
                        else:
                            cards = list(map(int, fields['cards_summary'].split(',')))
                            args = dict(item_id=fields['item_id'], amount=fields['amount'], identified=fields['identified'],
                                        refine=fields['refine'], attribute=r.number(11,'B'))
                            args.update({f'card{i+1}':value for i,value in enumerate(cards)})
                            emit('getitem2', args, review=True, reason=reason, slot_index=inventory_index, observed=fields)
                    elif fields['plain_item']:
                        emit('getitem', dict(item_id=fields['item_id'], amount=fields['amount']), slot_index=inventory_index, observed=fields)
                    else:
                        cards = list(map(int, fields['cards_summary'].split(',')))
                        args = dict(item_id=fields['item_id'], amount=fields['amount'], identified=fields['identified'],
                                    refine=fields['refine'], attribute=r.number(11,'B'))
                        args.update({f'card{i+1}':value for i,value in enumerate(cards)})
                        unsupported = bool(fields['grade'] or fields['expires'] or fields['bound'] or
                                           any(int(x.split(':')[0]) or int(x.split(':')[1]) for x in fields['options_summary'].split(',')))
                        emit('getitem2', args, review=unsupported, reason='grade・期限・binding・ランダムオプションはgetitem2で再現不可' if unsupported else '', slot_index=inventory_index, observed=fields)
        if pid in (0xaa,0x999,0xac,0x99a):
            modern = pid in (0x999,0x99a)
            expected = 11 if pid==0x999 else 9 if modern else 7 if pid==0xac else 9
            if len(packet.raw) != expected:
                raise ObservationError('Unsupported equipment response layout')
            inventory_index = r.number(2,'H'); mask=r.number(4,'I' if modern else 'H')
            flag=r.number(expected-1,'B')
            if flag not in (0,1):
                raise ObservationError('Unsupported equipment response result')
            success=flag==0 if modern else flag==1
            if len(state['inventory']) >= 4096 and inventory_index not in state['inventory']:
                raise ObservationError('Command inventory capacity reached')
            item=state['inventory'].setdefault(inventory_index,{})
            requested=state['pending'].pop(('unequip',inventory_index),None) if pid in (0xac,0x99a) else None
            if success:
                item['last_equip_mask']=mask
                if pid in (0xaa,0x999):
                    item['equip_mask']=mask
                else:
                    item['equip_mask']=0
                    if requested is None and not state.get('pending_incomplete'):
                        slot=self.policy['equip_slots'].get(str(mask))
                        emit('unequip',dict(slot=slot),review=slot is None,reason='装備部位が未確定' if slot is None else '',slot_index=inventory_index)
        if pid in (0xaf,0x7fa):
            decoded=decode_player(packet); fields=decoded[1]; inventory_index=fields['index']
            item=state['inventory'].get(inventory_index,{})
            manual_drop = state['pending'].pop(('drop',inventory_index),None) is not None
            cart_key = ('cart_from_body', inventory_index, fields['amount'])
            cart_move = state['pending'].pop(cart_key, None)
            if cart_move is None:
                # Same body index with a different requested amount stays unresolved.
                for key in list(state['pending']):
                    if isinstance(key, tuple) and len(key) == 3 and key[0] == 'cart_from_body' and key[1] == inventory_index:
                        state['pending_incomplete'] = True
                        break
            if conversation and not state['storage'] and not manual_drop and cart_move is None:
                index_cart_pending = any(isinstance(key, tuple) and len(key) == 3 and key[0] == 'cart_from_body'
                                         and key[1] == inventory_index for key in state['pending'])
                unequips=[old for old in state['recent'] if old['slot_index']==inventory_index and old['conversation_id']==conversation.id
                          and old['fields']['command']=='unequip' and not old['fields'].get('review_only') and nearby(old['timestamp'])]
                mask=item.get('equip_mask',0) or (item.get('last_equip_mask',0) if unequips else 0)
                slot=self.policy['equip_slots'].get(str(mask))
                if slot and fields['amount']==1 and not index_cart_pending:
                    for old in unequips:
                        self._suppress(old,'delequipに包含される装備解除を重複抑止')
                    emit('delequip',dict(slot=slot),slot_index=inventory_index,observed=dict(fields,item=item))
                else:
                    ambiguous_gear=item.get('list_family')=='equipment' or item.get('item_type') in (4,5,7)
                    review = not item.get('item_id') or ambiguous_gear or index_cart_pending
                    reason = ('カート格納要求と数量が一致せず消費との対応が未確定' if index_cart_pending else
                              '装備個体・装備部位または消失アイテムIDが未確定' if not item.get('item_id') or ambiguous_gear else '')
                    emit('delitem',dict(item_id=item.get('item_id'),amount=fields['amount']),review=review,
                         reason=reason,slot_index=inventory_index,observed=dict(fields,item=item))
            item['amount']=max(0,item.get('amount',fields['amount'])-fields['amount'])
            item['equip_mask']=0
        if pid == 0x188:
            if len(packet.raw)!=8:
                raise ObservationError('Invalid refine result length')
            result,inventory_index,after=(r.number(o,'H') for o in (2,4,6))
            if result not in (0,1,2):
                raise ObservationError('Unsupported refine result')
            item=state['inventory'].get(inventory_index,{})
            mask=item.get('equip_mask') or item.get('last_equip_mask')
            slot=self.policy['equip_slots'].get(str(mask)); before=item.get('refine')
            if conversation and result in (0,1,2):
                command={0:'successrefitem',1:'failedrefitem',2:'downrefitem'}[result]
                args=dict(slot=slot)
                if result==2:
                    args['decrement']=before-after if type(before) is int and before>after else None
                for old in list(state['recent']):
                    if (old['slot_index']==inventory_index and old['conversation_id']==conversation.id and nearby(old['timestamp'])
                        and old['fields']['command'] in ('unequip','delitem','delequip')):
                        self._suppress(old,'精錬結果に包含される処理のため重複命令を抑止')
                mismatch=result==0 and type(before) is int and after!=before+1
                emit(command,args,review=mismatch or slot is None or any(v is None for v in args.values()),
                     reason='装備部位・精錬前の値または結果差分が未確定' if mismatch or slot is None or any(v is None for v in args.values()) else '',
                     slot_index=inventory_index,observed=dict(result=result,before=before,after=after))
            item['refine']=after
        if pid in (0x8a,0x2e1,0x8c8):
            expected={0x8a:29,0x2e1:33,0x8c8:34}[pid]
            if len(packet.raw)==expected and world:
                action=r.number({0x8a:26,0x2e1:28,0x8c8:29}[pid],'B')
                player=world.player_maps.states.get(key)
                if action in (2,3) and player and r.number(2,'I')==player.actor_id:
                    requested=state['pending'].pop(('posture',action),None)
                    if requested is None and not state.get('pending_incomplete'):
                        emit('sit' if action==2 else 'stand',{})
        if pid in (0x9e,0x84b,0xadd):
            expected={0x9e:17,0x84b:19,0xadd:24}[pid]
            if len(packet.raw)!=expected:
                raise ObservationError('Unsupported floor item layout')
            floor_id=r.number(2,'I')
            if floor_id not in state['floor']:
                if len(state['floor'])>=4096:
                    raise ObservationError('Floor item capacity reached')
                state['floor'].add(floor_id)
                if not nearby(state['death']) and not nearby(state['pending'].get('drop')):
                    off=9 if pid==0x9e else 11 if pid==0x84b else 13
                    args=dict(map_name=scene.map_name if scene else None,x=r.number(off,'H'),y=r.number(off+2,'H'),
                              item_id=r.number(6,'I' if pid==0xadd else 'H'),amount=r.number(off+6,'H'),
                              extra_lifetime_ms=None)
                    desired=self.policy.get('dropitem_lifetime_ms'); base=self.policy.get('flooritem_base_lifetime_ms')
                    if desired is not None and base is not None:
                        args['extra_lifetime_ms']=desired-base
                    review=not state['settled'] or args['extra_lifetime_ms'] is None or args['map_name'] is None
                    record=emit('dropitem',args,review=review,reason='初回視界の出現・寿命設定・MAPの確認が必要' if review else '',observed=dict(floor_id=floor_id))
                    record['fields'].update(lifetime_ms=desired,base_lifetime_ms=base)
        return out
