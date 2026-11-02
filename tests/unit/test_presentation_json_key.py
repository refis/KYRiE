import unittest

from gui.dialogues import presentation_document_key
from reconstruction.dialogue import DialogueStore


class PresentationJsonKeyTests(unittest.TestCase):
    def test_revision_alone_does_not_change_presentation_key(self):
        store = DialogueStore()
        first = presentation_document_key(store)
        store.revision += 1
        self.assertEqual(presentation_document_key(store), first)

    def test_presentation_append_changes_key(self):
        store = DialogueStore()
        before = presentation_document_key(store)
        store.presentation_observations.append(dict(packet_index=9, kind='announcement'))
        store.revision += 1
        self.assertNotEqual(presentation_document_key(store), before)
