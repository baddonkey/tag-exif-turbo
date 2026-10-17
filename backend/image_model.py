from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class ImageModel(QAbstractListModel):
    roles = {Qt.ItemDataRole.UserRole + 1: b"filename", Qt.ItemDataRole.UserRole + 2: b"imageId"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._images: list[dict] = []

    def roleNames(self) -> dict[int, bytes]:
        return self.roles

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._images)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._images):
            return None
        image = self._images[index.row()]
        return image.get("filename") if role == Qt.ItemDataRole.UserRole + 1 else image.get("id") if role == Qt.ItemDataRole.UserRole + 2 else None

    def show(self, image: dict) -> None:
        self.beginResetModel()
        self._images = [{"id": image["id"], "filename": image["filename"]}]
        self.endResetModel()