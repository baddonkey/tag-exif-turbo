import unicodedata
from collections.abc import Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


def normalize_tag(value: str) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    if len(value) > 160 or any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("Tags must be under 161 characters and contain no control characters.")
    return value


def clean_tags(values: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = normalize_tag(value)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            result.append(cleaned)
    return result


class TagModel(QAbstractListModel):
    LabelRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tags: list[str] = []

    def roleNames(self) -> dict[int, bytes]:
        return {self.LabelRole: b"label"}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tags)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and 0 <= index.row() < len(self._tags) and role in {self.LabelRole, Qt.ItemDataRole.DisplayRole}:
            return self._tags[index.row()]
        return None

    def values(self) -> list[str]:
        return self._tags.copy()

    def replace(self, values: Iterable[str]) -> None:
        tags = clean_tags(values)
        self.beginResetModel()
        self._tags = tags
        self.endResetModel()

    def add(self, value: str) -> bool:
        tag = normalize_tag(value)
        if not tag or tag.casefold() in {item.casefold() for item in self._tags}:
            return False
        offset = len(self._tags)
        self.beginInsertRows(QModelIndex(), offset, offset)
        self._tags.append(tag)
        self.endInsertRows()
        return True

    def remove(self, value: str) -> bool:
        if value not in self._tags:
            return False
        offset = self._tags.index(value)
        self.beginRemoveRows(QModelIndex(), offset, offset)
        self._tags.pop(offset)
        self.endRemoveRows()
        return True