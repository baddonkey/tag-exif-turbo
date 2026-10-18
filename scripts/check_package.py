import argparse
import os
import subprocess
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path


def verify_wheel(root: Path, wheel: Path) -> str:
    with (root / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("main.py") == (root / "main.py").read_bytes()
        for directory in ("qml", "assets"):
            for source in (root / directory).rglob("*"):
                if source.is_file():
                    bundled = f"backend/resources/{source.relative_to(root).as_posix()}"
                    assert archive.read(bundled) == source.read_bytes(), f"Stale packaged resource: {bundled}"
        assert archive.read("backend/desktop.py") == (root / "backend/desktop.py").read_bytes()
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify built wheel resources and isolated installed startup")
    parser.add_argument("wheel", type=Path, help="Wheel file or a directory containing exactly one wheel")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    wheels = list(args.wheel.glob("*.whl")) if args.wheel.is_dir() else [args.wheel]
    if len(wheels) != 1:
        parser.error("Expected exactly one wheel")
    wheel = wheels[0].resolve()
    version = verify_wheel(root, wheel)
    with tempfile.TemporaryDirectory(prefix="tagger-package-") as directory:
        temporary = Path(directory)
        environment = temporary / "environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        launcher = scripts / ("tag-exif-turbo.exe" if os.name == "nt" else "tag-exif-turbo")
        settings = temporary / "settings"
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_CONTROLS_STYLE": "Basic",
               "PYTHONUTF8": "1", "HOME": str(temporary), "USERPROFILE": str(temporary),
               "APPDATA": str(temporary / "roaming"), "LOCALAPPDATA": str(temporary / "local"),
               "XDG_CONFIG_HOME": str(settings), "XDG_DATA_HOME": str(temporary / "data")}
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=temporary, env=env, check=True, timeout=120)
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], cwd=temporary, env=env, check=True, timeout=300)
        result = subprocess.run([str(launcher), "--version"], cwd=temporary, env=env, check=True,
                                capture_output=True, text=True, timeout=30)
        assert version in result.stdout, result.stdout
        bootstrap = """
import sys
from pathlib import Path
from PySide6.QtCore import QSettings, QStandardPaths
QStandardPaths.setTestModeEnabled(True)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, sys.argv[1])
import main
assert Path(main.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
sys.argv = ['tag-exif-turbo', '--smoke']
raise SystemExit(main.main())
"""
        subprocess.run([str(python), "-I", "-c", bootstrap, str(settings)], cwd=temporary,
                       env=env, check=True, timeout=45)
    print(f"Verified wheel {wheel.name}: resources match source; installed version and offline startup passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())