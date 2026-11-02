import struct
import unittest

from parser.display import ReceiveDisplay, DisplayProfile, DEFAULT_PROFILE
from reconstruction.auriga import AurigaRenderer
from reconstruction.dialogue import DialogueStore
from reconstruction.identity_protection import (
    apply_to_display_values, identity_from_player, quote_text, script_text, templates)
from reconstruction.world import WorldStore
from tests.support.dialogue import packet
from tests.support.player import character_list
from tests.support.world import actor_packet, map_packet


class IdentityProtectionTests(unittest.TestCase):
    def test_script_text_replaces_known_identity_longest_first(self):
        identity = dict(character_name='太郎', party_name='太郎党', guild_name='ギルドA')
        self.assertEqual(
            script_text('ようこそ、太郎さん。ギルドA / 太郎党', identity),
            '"ようこそ、"+getstrcharinfo(0)+"さん。"+getstrcharinfo(2)+" / "+getstrcharinfo(1)')
        self.assertEqual(script_text('無関係', identity), '"無関係"')
        self.assertEqual(quote_text('太郎', identity), 'getstrcharinfo(0)')
        rathena = templates('config/rathena/identity_protection.json')
        self.assertEqual(rathena['expressions']['character_name'], 'strcharinfo(0)')
        self.assertEqual(
            script_text('太郎', {'character_name': '太郎'}, 'config/rathena/identity_protection.json'),
            'strcharinfo(0)')

    def test_display_mes_and_actor_comments_use_protection(self):
        display = ReceiveDisplay(DisplayProfile.load(DEFAULT_PROFILE))
        players = display.players
        from tests.support.player import packet as player_packet
        players.apply(player_packet(0x65, struct.pack('<I', 42) + bytes(11), direction='SEND', flow='char'))
        players.apply(character_list(name='ヘッドハンター'), packet_index=1)
        players.apply(player_packet(0x436, struct.pack('<II', 42, 123) + bytes(13),
                                    direction='SEND', flow='flow-a'), packet_index=2)
        state = players.states[(0, 'flow-a')]
        self.assertEqual(state.character_name, 'ヘッドハンター')
        self.assertEqual(state.actor_id, 42)
        state.party_name = '夜行組'
        state.guild_name = '検証ギルド'
        body = 'ようこそ、ヘッドハンター。夜行組／検証ギルド'
        mes = packet(0xb4, struct.pack('<I', 7) + body.encode('cp932') + b'\0',
                     flow='flow-a', connection='flow-a')
        result = display.decode(mes)
        expected = 'mes ' + script_text(body, identity_from_player(state)) + ';'
        self.assertEqual(result.text, expected)
        self.assertEqual(result.fields['text'], body)
        emotion = packet(0xc0, struct.pack('<IB', 42, 1), flow='flow-a', connection='flow-a')
        shown = display.decode(emotion)
        self.assertEqual(shown.text, '@emotion 1;\t// self')
        self.assertEqual(shown.fields['actor_id'], 42)

    def test_code_generation_protects_mes_menu_and_keeps_raw_steps(self):
        world = WorldStore()
        dialogues = DialogueStore(world=world)
        events = [
            map_packet(), actor_packet(),
            packet(0x90, struct.pack('<IB', 42, 1), 'SEND', flow='flow-a', connection='flow-a'),
            packet(0xb4, struct.pack('<I', 42) + 'こんにちは、英雄さん\0'.encode('cp932'),
                   flow='flow-a', connection='flow-a'),
            packet(0xb7, struct.pack('<I', 42) + '英雄の家:やめる\0'.encode('cp932'),
                   flow='flow-a', connection='flow-a'),
            packet(0xb8, struct.pack('<IB', 42, 2), 'SEND', flow='flow-a', connection='flow-a'),
            packet(0xb6, struct.pack('<I', 42), flow='flow-a', connection='flow-a'),
        ]
        for index, event in enumerate(events):
            world.apply(event, packet_index=index)
            dialogues.apply(event, packet_index=index)
        item = dialogues.sessions[0]
        identity = dict(character_name='英雄', actor_id=7)
        code = AurigaRenderer(identity=identity).render(item)
        self.assertIn('mes "こんにちは、"+getstrcharinfo(0)+"さん";', code)
        self.assertIn('menu(getstrcharinfo(0)+"の家","やめる")', code)
        mes = next(step['fields']['text'] for step in item.steps if step['kind'] == 'mes')
        self.assertEqual(mes, 'こんにちは、英雄さん')
        plain = AurigaRenderer().render(item)
        self.assertIn('mes "こんにちは、英雄さん";', plain)

    def test_display_values_helper_marks_protected_text(self):
        values = apply_to_display_values(
            dict(text='A太郎B', actor_id=5, target_id=9),
            dict(character_name='太郎', actor_id=5))
        self.assertEqual(values['text'], '"A"+getstrcharinfo(0)+"B"')
        self.assertTrue(values['_protect_text_text'])
        self.assertEqual(values['actor_id'], 'self')
        self.assertEqual(values['target_id'], 9)
