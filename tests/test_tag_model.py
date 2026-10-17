from PySide6.QtCore import QModelIndex
from PySide6.QtTest import QSignalSpy

from backend.tag_model import TagModel


def test_tags_normalize_and_notify():
    model = TagModel()
    inserted = QSignalSpy(model.rowsInserted)
    assert model.add("  Trees  ")
    assert not model.add("trees")
    assert model.rowCount() == 1
    assert model.rowCount(model.index(0)) == 0
    assert model.data(model.index(0), model.LabelRole) == "Trees"
    assert model.data(QModelIndex()) is None
    assert inserted.count() == 1
    removed = QSignalSpy(model.rowsRemoved)
    assert model.remove("Trees")
    assert removed.count() == 1