from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


try:
    __version__ = version("tag-exif-turbo")
except PackageNotFoundError:
    with (Path(__file__).parent.parent / "pyproject.toml").open("rb") as manifest:
        __version__ = tomllib.load(manifest)["project"]["version"]