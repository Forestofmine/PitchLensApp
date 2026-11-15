import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.ui.editor import ScoreEditorDialog


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_dialog(self) -> ScoreEditorDialog:
        score = parse_jianpu_text("1=C 4/4 90\n| 1 2 3 5 | 6 5 3 - |").score
        return ScoreEditorDialog(score, None)

    def test_apply_button_saves_and_closes(self):
        # Regression: QDialogButtonBox emits accepted() only for AcceptRole
        # buttons; Apply has ApplyRole, so it must be wired via clicked().
        dlg = self._make_dialog()
        dlg.table.item(0, 2).setText("2")  # 音级 1 → 2
        box = dlg.findChild(QDialogButtonBox)
        box.button(QDialogButtonBox.StandardButton.Apply).click()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertIsNotNone(dlg.result_score)
        self.assertEqual(dlg.result_score.notes[0].degree, 2)

    def test_cell_edit_is_undoable(self):
        dlg = self._make_dialog()
        self.assertEqual(dlg.score.notes[0].degree, 1)
        dlg.table.item(0, 2).setText("5")
        self.assertEqual(dlg.score.notes[0].degree, 5)
        dlg._undo()
        self.assertEqual(dlg.score.notes[0].degree, 1)
        dlg._redo()
        self.assertEqual(dlg.score.notes[0].degree, 5)

    def test_delete_undo_redo(self):
        dlg = self._make_dialog()
        original = len(dlg.score.notes)
        dlg.table.selectRow(0)
        dlg._delete_selected()
        self.assertEqual(len(dlg.score.notes), original - 1)
        dlg._undo()
        self.assertEqual(len(dlg.score.notes), original)
        self.assertEqual(dlg.score.notes[0].degree, 1)
        dlg._redo()
        self.assertEqual(len(dlg.score.notes), original - 1)

    def test_add_note_undo(self):
        dlg = self._make_dialog()
        original = len(dlg.score.notes)
        dlg._add_note()
        self.assertEqual(len(dlg.score.notes), original + 1)
        dlg._undo()
        self.assertEqual(len(dlg.score.notes), original)

    def test_insert_after_selected(self):
        dlg = self._make_dialog()
        original = len(dlg.score.notes)  # 8 notes: | 1 2 3 5 | 6 5 3 - |
        dlg.table.selectRow(1)  # anchor = second note (degree 2)
        anchor = dlg.score.notes[1]
        following = dlg.score.notes[2]
        dlg._add_note()
        self.assertEqual(len(dlg.score.notes), original + 1)
        self.assertIs(dlg.score.notes[1], anchor)
        new_note = dlg.score.notes[2]
        self.assertIsNot(new_note, anchor)
        self.assertIsNot(new_note, following)
        self.assertEqual(new_note.degree, anchor.degree)
        self.assertEqual(new_note.duration_beat, anchor.duration_beat)
        self.assertEqual(new_note.measure_index, anchor.measure_index)
        # The note after the inserted one is the old follower; order kept.
        self.assertIs(dlg.score.notes[3], following)
        # The new row is selected in the table.
        selected = dlg.table.selectionModel().selectedRows()
        self.assertTrue(selected)
        self.assertIs(dlg.score.notes[selected[0].row()], new_note)
        dlg._undo()
        self.assertEqual(len(dlg.score.notes), original)
        self.assertIs(dlg.score.notes[1].degree, anchor.degree)

    def test_duration_toolbar(self):
        dlg = self._make_dialog()
        dlg.table.selectRow(0)
        original = dlg.score.notes[0].duration_beat
        # Quick-button path.
        dlg._set_duration_for_selected(0.5)
        self.assertAlmostEqual(dlg.score.notes[0].duration_beat, 0.5)
        self.assertEqual(dlg.table.item(0, 5).text(), "0.5")
        # Combo named-choice path.
        index = dlg.duration_combo.findText("附点4分音符")
        self.assertGreaterEqual(index, 0)
        dlg._on_duration_combo_activated(index)
        self.assertAlmostEqual(dlg.score.notes[0].duration_beat, 1.5)
        # Typed custom value path.
        dlg.duration_combo.setCurrentText("0.75")
        dlg._on_duration_text_entered()
        self.assertAlmostEqual(dlg.score.notes[0].duration_beat, 0.75)
        # Garbage input leaves the value untouched.
        dlg.duration_combo.setCurrentText("abc")
        dlg._on_duration_text_entered()
        self.assertAlmostEqual(dlg.score.notes[0].duration_beat, 0.75)
        # Undo unwinds all three changes.
        dlg._undo()
        self.assertAlmostEqual(dlg.score.notes[0].duration_beat, 1.5)
        dlg._undo()
        self.assertAlmostEqual(dlg.score.notes[0].duration_beat, 0.5)
        dlg._undo()
        self.assertAlmostEqual(dlg.score.notes[0].duration_beat, original)

    def test_measure_edit_reorder_keeps_table_consistent(self):
        # Regression: editing the measure column re-sorts notes; the table
        # must be rebuilt or rows and notes drift apart.
        dlg = self._make_dialog()
        dlg.table.item(0, 1).setText("3")  # 移到第 3 小节，触发重排
        self.assertEqual(dlg.table.rowCount(), len(dlg.score.notes))
        for row, note in enumerate(dlg.score.notes):
            self.assertEqual(dlg.table.item(row, 1).text(), str(note.measure_index + 1))
            self.assertEqual(dlg.table.item(row, 2).text(), str(note.degree))
        # 被编辑的音符（唯一在第 3 小节的）在重排后仍被选中
        # （注意 refresh() 会按顺序重排 id，不能用 id 判断）
        selected = dlg.table.selectionModel().selectedRows()
        self.assertTrue(selected)
        self.assertEqual(dlg.score.notes[selected[0].row()].measure_index, 2)


if __name__ == "__main__":
    unittest.main()
