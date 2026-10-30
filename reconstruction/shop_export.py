"""Auriga review candidates using an explicitly confirmed client-ID identity map."""
from reconstruction.render_inputs import read_render_json
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from string import Formatter

from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import conversation_path
from reconstruction.npc_initial_state import visibility_state
from reconstruction.actor_appearance import player_class

DEFAULT_SHOP_PROFILE = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'shops.json'
FIELDS = {'review': {'map_origin'},
          'placed_shop': {'map_name', 'x', 'y', 'direction', 'npc_name', 'class_id', 'items'},
          'hidden_shop': {'shop_name', 'items'}}
FIELDS['initial_display_review'] = set()
FIELDS['initial_state_review'] = {'state', 'options'}
FIELDS['review_unconfirmed'] = {'map_origin'}


def shop_name_for(npc, items):
    placement = AurigaRenderer.placement_values(npc)
    products = [f'{item["client_item_id"]}:{item["price"]}' for item in items]
    identity = json.dumps([placement, products], ensure_ascii=False, sort_keys=True).encode('utf-8')
    return 'GPA_S' + hashlib.sha256(identity).hexdigest()[:12]


class ShopRenderer:
    def __init__(self, path=None):
        from reconstruction.emulator_profiles import profile
        path = Path(path) if path is not None else profile('shops.json')
        self.templates = read_render_json(path)
        if isinstance(self.templates, dict):
            defaults = read_render_json(DEFAULT_SHOP_PROFILE)
            for key in ('initial_state_review', 'review_unconfirmed', 'initial_display_review'):
                self.templates.setdefault(key, defaults[key])
        if not isinstance(self.templates, dict) or set(self.templates) != set(FIELDS):
            raise ValueError('ショップ書式の項目が不正です。')
        for key, value in self.templates.items():
            if not isinstance(value, str) or len(value) > 65536:
                raise ValueError('ショップ書式が不正です。')
            for _, name, spec, conversion in Formatter().parse(value):
                if name is not None and (name not in FIELDS[key] or spec or conversion):
                    raise ValueError('ショップ書式の引数が不正です。')

    def render(self, record, mode, *, item_ids_confirmed=False, map_name=None, conversation=None, review_unconfirmed=False):
        if mode not in ('shop', 'callshop') or (item_ids_confirmed is not True and review_unconfirmed is not True):
            raise ValueError('生成形式と出力先DBの商品ID対応を確認してください。')
        if record['association'] != 'selector_and_buy_reply':
            raise ValueError('対象選択と購入応答を確認できる一覧を選択してください。')
        linked = record.get('conversation_id')
        if linked is not None:
            if (conversation is None or conversation.id != linked
                    or conversation.capture_session != record['capture_session']
                    or conversation.flow_id != record['flow_id'] or conversation.status != 'shop_opened'
                    or not record['association_evidence']
                    or conversation.termination.get('packet_index') != record['association_evidence'][0]['packet_index']
                    or conversation.termination.get('shop_actor_id') != record['actor_id']):
                raise ValueError('対応する会話からショップへの遷移が一致しません。')
        has_dialogue = bool(conversation and any(step['kind'] not in ('open', 'dismiss') for step in conversation.steps))
        if mode == 'callshop' and (linked is None or not has_dialogue):
            raise ValueError('callshop形式には本文を伴う対応会話が必要です。')
        if mode == 'callshop':
            if not conversation.observed_open or conversation.issues:
                raise ValueError('会話開始・応答・解析問題を確認してください。')
            tokens = conversation_path('', conversation)
            if any(token['kind'] in ('pending', 'ambiguous') for token in tokens):
                raise ValueError('応答が未観測のためcallshop位置を確定できません。')
        if mode == 'shop' and has_dialogue:
            raise ValueError('本文を伴う経路にはcallshop形式を選択してください。')
        npc = deepcopy(conversation.npc if mode == 'callshop' else record['npc'])
        manual_map = not npc.get('map_name')
        if manual_map:
            npc['map_name'] = map_name
        elif map_name is not None and map_name != npc['map_name']:
            raise ValueError('観測済みマップ名を上書きできません。')
        placement = AurigaRenderer.placement_values(npc)
        if not record['items'] or len(record['items']) > 2048:
            raise ValueError('商品数が不正です。')
        products, seen = [], set()
        for item in record['items']:
            item_id, price = item['client_item_id'], item['price']
            if (type(item_id) is not int or not 1 <= item_id <= 2147483647 or type(price) is not int
                    or not 0 <= price <= 2147483647 or item_id in seen):
                raise ValueError('商品ID・基本価格・重複掲載を確認してください。')
            seen.add(item_id)
            products.append(f'{item_id}:{price}')
        items = ','.join(products)
        review = self.templates['review' if item_ids_confirmed else 'review_unconfirmed'].format_map(dict(map_origin='利用者入力' if manual_map else '観測'))
        if mode == 'shop':
            result = review + '\n' + self.templates['placed_shop'].format_map(dict(placement, items=items)) + '\n'
            if player_class((npc.get('initial_display') or {}).get('class_id',npc.get('class_id'))):
                result = self.templates['initial_display_review'] + '\n' + '\n'.join('// '+line for line in result.splitlines())+'\n'
            state = visibility_state(npc)
            if state in ('hidden', 'cloaked', 'ambiguous'):
                warning = self.templates['initial_state_review'].format(state=state, options=npc['initial_options'])
                result = warning + '\n' + '\n'.join('// ' + line for line in result.splitlines()) + '\n'
        else:
            shop_name = shop_name_for(npc, record['items'])
            copied = deepcopy(conversation)
            copied.npc = npc
            body = AurigaRenderer().render_npc_file(copied, shop_call_name=shop_name)
            result = (review + '\n' + self.templates['hidden_shop'].format_map(dict(shop_name=shop_name, items=items))
                      + '\n\n' + body)
        if len(result) > 4 * 1024 * 1024:
            raise ValueError('ショップ候補が出力上限を超えています。')
        return result
