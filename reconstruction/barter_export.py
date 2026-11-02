"""Auriga review candidates for expanded barter lists (always commented)."""
from reconstruction.render_inputs import read_render_json
from copy import deepcopy
import json
from pathlib import Path
from string import Formatter

from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import conversation_path

DEFAULT_BARTER_PROFILE = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'barters.json'
FIELDS = {
    'review': {'map_origin'},
    'review_unconfirmed': {'map_origin'},
    'hidden_barter': {'shop_name', 'items'},
    'callbarter_review': {'shop_name'},
}


def script_refine(value):
    """Wire refine 0 is emitted as -1 to match published barter script samples."""
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError('通貨の精錬値が不正です。')
    return -1 if value == 0 else value


def format_barter_items(items):
    products = []
    seen = set()
    for item in items:
        item_id, stock, zeny = item['client_item_id'], item['stock'], item['zeny']
        if (type(item_id) is not int or not 1 <= item_id <= 2147483647 or item_id in seen
                or type(stock) is not int or not (-1 == stock or 0 <= stock <= 2147483647)
                or type(zeny) is not int or not 0 <= zeny <= 2147483647):
            raise ValueError('商品ID・在庫・zeny・重複掲載を確認してください。')
        seen.add(item_id)
        currencies = item.get('currencies') or []
        if not currencies or len(currencies) > 64:
            raise ValueError('通貨構成が不正です。')
        parts = []
        for currency in currencies:
            currency_id, amount = currency['client_item_id'], currency['amount']
            refine = script_refine(currency['refine_level'])
            if (type(currency_id) is not int or not 1 <= currency_id <= 2147483647
                    or type(amount) is not int or not 1 <= amount <= 2147483647):
                raise ValueError('通貨ID・個数を確認してください。')
            parts.append(f'{currency_id}:{refine}:{amount}')
        products.append(f'{item_id}:{stock}:{zeny} {{ {",".join(parts)} }}')
    return ','.join(products)


def barter_name_for(npc, items):
    placement = AurigaRenderer.placement_values(npc)
    # items remain validated by callers; name is map-scoped per callbarter rule.
    format_barter_items(items)
    name = f"{placement['map_name']}#callbarter"
    if not isinstance(name, str) or len(name.encode('cp932', errors='strict')) > 23:
        raise ValueError('callbarter用NPC名が候補出力の上限23バイトを超えています。')
    return name


class BarterRenderer:
    def __init__(self, path=None):
        from reconstruction.emulator_profiles import profile
        path = Path(path) if path is not None else profile('barters.json')
        self.templates = read_render_json(path)
        if isinstance(self.templates, dict):
            defaults = read_render_json(DEFAULT_BARTER_PROFILE)
            for key in FIELDS:
                self.templates.setdefault(key, defaults[key])
        if not isinstance(self.templates, dict) or set(self.templates) != set(FIELDS):
            raise ValueError('barter書式の項目が不正です。')
        for key, value in self.templates.items():
            if not isinstance(value, str) or len(value) > 65536:
                raise ValueError('barter書式が不正です。')
            for _, name, spec, conversion in Formatter().parse(value):
                if name is not None and (name not in FIELDS[key] or spec or conversion):
                    raise ValueError('barter書式の引数が不正です。')

    def render(self, record, *, item_ids_confirmed=False, map_name=None, conversation=None, review_unconfirmed=False):
        if item_ids_confirmed is not True and review_unconfirmed is not True:
            raise ValueError('出力先DBの商品ID対応を確認してください。')
        if (record.get('market_kind') not in ('expanded_barter', 'barterlist')
                or record.get('association') != 'after_close_list'):
            raise ValueError('close直後のbarter一覧対応を確認できる記録を選択してください。')
        linked = record.get('conversation_id')
        if (conversation is None or conversation.id != linked
                or conversation.capture_session != record['capture_session']
                or conversation.flow_id != record['flow_id'] or conversation.status != 'barter_opened'
                or not record['association_evidence']
                or conversation.termination.get('packet_index') != record['association_evidence'][0]['packet_index']
                or conversation.termination.get('shop_actor_id') != record['actor_id']
                or record.get('conversation_link_basis') != 'same_flow_after_close'
                or conversation.termination.get('shop_link_basis') != 'same_flow_after_close'
                or conversation.termination.get('after_close_barter') is not True
                or conversation.termination.get('market_kind') != record.get('market_kind')):
            raise ValueError('対応する会話からbarterへの遷移が一致しません。')
        if not conversation.observed_open or conversation.issues:
            raise ValueError('会話開始・応答・解析問題を確認してください。')
        if not any(step['kind'] not in ('open', 'dismiss') for step in conversation.steps):
            raise ValueError('本文を伴う対応会話が必要です。')
        tokens = conversation_path('', conversation)
        if any(token['kind'] in ('pending', 'ambiguous') for token in tokens):
            raise ValueError('応答が未観測のためbarter位置を確定できません。')
        npc = deepcopy(conversation.npc)
        manual_map = not npc.get('map_name')
        if manual_map:
            npc['map_name'] = map_name
        elif map_name is not None and map_name != npc['map_name']:
            raise ValueError('観測済みマップ名を上書きできません。')
        AurigaRenderer.placement_values(npc)
        if not record['items'] or len(record['items']) > 2048:
            raise ValueError('商品数が不正です。')
        items = format_barter_items(record['items'])
        shop_name = barter_name_for(npc, record['items'])
        review_key = 'review' if item_ids_confirmed else 'review_unconfirmed'
        review = self.templates[review_key].format_map(dict(map_origin='利用者入力' if manual_map else '観測'))
        hidden = self.templates['hidden_barter'].format_map(dict(shop_name=shop_name, items=items))
        copied = deepcopy(conversation)
        copied.npc = npc
        copied.termination = dict(copied.termination, barter_call_name=shop_name)
        body = AurigaRenderer().render_npc_file(copied)
        result = review + '\n' + hidden + '\n\n' + body
        if len(result) > 4 * 1024 * 1024:
            raise ValueError('barter候補が出力上限を超えています。')
        return result

    def hidden_definition(self, record, npc):
        items = format_barter_items(record['items'])
        name = barter_name_for(npc, record['items'])
        return name, self.templates['hidden_barter'].format_map(dict(shop_name=name, items=items))
