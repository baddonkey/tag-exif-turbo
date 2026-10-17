from collections import OrderedDict
from threading import Lock

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class ImageProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lock = Lock()
        self._images: OrderedDict[str, QImage] = OrderedDict()

    def store(self, key: str, image: QImage) -> str:
        with self._lock:
            self._images[key] = image.copy()
            while len(self._images) > 3:
                self._images.popitem(last=False)
        return f"image://preview/{key}"

    def requestImage(self, identifier: str, size: QSize, requestedSize: QSize) -> QImage:
        with self._lock:
            image = self._images.get(identifier, QImage()).copy()
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image