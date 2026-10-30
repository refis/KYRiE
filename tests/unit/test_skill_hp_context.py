from copy import deepcopy
import unittest
from reconstruction.skill_hp_context import skill_hp_contexts,compare_percentage


def skill(index=10,time=2,key=(0,'receive',1,42,1),cls=1005):
    return dict(entity_key=key,class_id=cls,packet_index=index,timestamp=time,flags=[])


def percent(value=50,index=5,time=1,key=(0,'receive',1,42,1),cls=1005,flags=()):
    return dict(skill(index,time,key,cls),packet_id=0xa36,role='state',hp_percent=value,flags=list(flags))


class SkillHPContextTests(unittest.TestCase):
    def test_percentage_uses_only_previous_same_entity_and_class_and_preserves_evidence(self):
        skills=[skill()]
        rows=[percent(50),percent(20,index=11,time=3),percent(10,index=6,key=(0,'receive',1,43,1)),
              percent(5,index=7,key=(0,'receive',1,42,2)),percent(15,index=8,cls=1006)]
        before=deepcopy((skills,rows))
        context=skill_hp_contexts(skills,rows)[0]
        self.assertEqual((context['hp_percent'],context['packet_index'],context['age_ms']),(50,5,1000))
        self.assertTrue(compare_percentage(context,50,'le'))
        self.assertTrue(compare_percentage(context,50,'ge'))
        self.assertFalse(compare_percentage(context,49,'le'))
        self.assertFalse(context['condition_confirmed'])
        self.assertEqual((skills,rows),before)

    def test_invalid_latest_percentage_or_time_does_not_fall_back_to_old_valid_value(self):
        for row,status in ((percent(1275,index=6,flags=('invalid_hp_percent',)),'invalid_percent'),
                           (percent(40,index=6,time=3),'invalid_time'),
                           (percent(40,index=6,flags=('assumed_boundary',)),'quality_warning')):
            with self.subTest(status=status):
                context=skill_hp_contexts([skill()],[percent(50),row])[0]
                self.assertEqual(context['packet_index'],6)
                self.assertEqual(context['status'],status)
                self.assertIsNone(compare_percentage(context,50,'le'))
        self.assertEqual(skill_hp_contexts([skill()],[])[0]['status'],'not_observed')
        self.assertEqual(skill_hp_contexts([skill()],[dict(percent(),packet_id=0x977)])[0]['status'],'not_observed')

    def test_class_roundtrip_and_incomplete_history_invalidate_old_percentage(self):
        changes=[dict(kind='MOB',capture_session=0,connection='receive',map_generation=1,actor_id=42,
                      packet_index=8,changes={'class_id':{'before':1005,'after':1006}}),
                 dict(kind='MOB',capture_session=0,connection='receive',map_generation=1,actor_id=42,
                      packet_index=9,changes={'class_id':{'before':1006,'after':1005}})]
        context=skill_hp_contexts([skill()],[percent()],changes)[0]
        self.assertEqual(context['status'],'class_changed')
        self.assertEqual(context['class_change_packet_index'],9)
        self.assertIsNone(compare_percentage(context,50,'ge'))
        self.assertEqual(skill_hp_contexts([skill()],[percent(index=9)],changes)[0]['status'],'observed')
        self.assertEqual(skill_hp_contexts([skill()],[percent()],history_complete=False)[0]['status'],'quality_warning')
