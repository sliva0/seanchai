"""The two packages as they would be published: what the built distributions
hold, and that the wheels work with nothing of the repository importable.

No network: uv builds with its bundled backend while the running uv is inside
`uv_build`'s bound, and the wheels' dependencies come from this environment.
The CI step installing the wheels from the index covers the declared ones.
"""

import datetime
import os
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
import seanchai_corpus
from conftest import _CORPUS_DIR, _ROOT

_UV = os.environ.get("UV") or shutil.which("uv")
_SMOKE = _ROOT / "tests" / "smoke_installed.py"
_PACKAGE = _ROOT / "packages" / "seanchai-corpus"
_LIBRARY = _ROOT / "src" / "seanchai"


def _project(pyproject: Path) -> dict:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]


def _uv(*arguments: object, cwd: Path) -> None:
    assert _UV, "the packaging tests run uv, which is not on PATH"
    subprocess.run(
        [_UV, *map(str, arguments)],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def dist(tmp_path_factory) -> Path:
    """Both packages built as the release workflow builds them. uv builds each
    wheel from its sdist, so a file the sdist drops is missing from the wheel."""
    output = tmp_path_factory.mktemp("dist")
    _uv("build", "--all-packages", "--no-sources", "--out-dir", output, cwd=_ROOT)
    return output


def _wheel(dist: Path, prefix: str) -> Path:
    (wheel,) = dist.glob(f"{prefix}-*.whl")
    return wheel


def _files(wheel: Path) -> set[str]:
    """A wheel's files, its metadata aside."""
    with zipfile.ZipFile(wheel) as archive:
        return {
            name
            for name in archive.namelist()
            if not name.endswith("/") and ".dist-info/" not in name
        }


def _requirements(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        (name,) = (n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = archive.read(name).decode("utf-8")
    return [
        line.removeprefix("Requires-Dist: ")
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist: ")
    ]


def _venv(root: Path, *wheels: Path) -> Path:
    """A virtual environment holding `wheels`, then this environment's packages
    for their dependencies. A path a `.pth` names goes after the environment's
    own and has its own `.pth` files left unread, so this repository's editable
    installs stay out of reach."""
    _uv("venv", "--python", sys.executable, root, cwd=root.parent)
    _uv(
        "pip",
        "install",
        "--python",
        root / "bin" / "python",
        "--no-deps",
        "--offline",
        *wheels,
        cwd=root.parent,
    )
    (site,) = root.glob("lib/python*/site-packages")
    (site / "_dependencies.pth").write_text(sysconfig.get_path("purelib") + "\n")
    return root / "bin"


def _clean_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if name not in {"PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME"}
    }


def test_the_corpus_wheel_holds_the_corpus_and_nothing_else(dist):
    corpus_files = {
        path.relative_to(_CORPUS_DIR).as_posix()
        for path in _CORPUS_DIR.rglob("*")
        if path.is_file()
    }

    assert "holes.toml" in corpus_files
    assert "rfc/rfc6733.dad" in corpus_files
    assert "raw/rfc/rfc6733.raw.dad" in corpus_files
    assert all(name == "holes.toml" or name.endswith(".dad") for name in corpus_files)
    assert _files(_wheel(dist, "seanchai_corpus")) == {
        "seanchai_corpus/__init__.py",
        "seanchai_corpus/py.typed",
        *(f"seanchai_corpus/dad/{name}" for name in corpus_files),
    }


def test_the_library_wheel_holds_the_library_and_no_data(dist):
    expected = {
        path.relative_to(_LIBRARY.parent).as_posix()
        for path in _LIBRARY.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    files = _files(_wheel(dist, "seanchai"))

    assert files == expected
    assert "seanchai/downloader/specs.toml" in files
    assert not any(name.endswith(".dad") for name in files)


@pytest.mark.parametrize("prefix", ["seanchai", "seanchai_corpus"])
def test_a_source_distribution_holds_the_package_and_its_metadata_only(dist, prefix):
    (sdist,) = dist.glob(f"{prefix}-*.tar.gz")

    with tarfile.open(sdist) as archive:
        top = {part for member in archive.getnames() for part in member.split("/")[1:2]}

    assert {"PKG-INFO", "README.md", "LICENSE", "src", "pyproject.toml"} <= top
    assert all(
        name in {"PKG-INFO", "README.md", "LICENSE", "src"}
        or name.startswith("pyproject.toml")
        for name in top
    )


def test_the_corpus_version_is_the_date_it_names():
    version = _project(_PACKAGE / "pyproject.toml")["version"]

    year, month, day = map(int, version.split("."))
    datetime.date(year, month, day)  # refuses what names no day
    # PEP 440 normalizes 2026.11.02 away, so the file keeps the published form.
    assert version == f"{year}.{month}.{day}"


def test_the_corpus_version_is_stored_once():
    version = _project(_PACKAGE / "pyproject.toml")["version"]

    assert seanchai_corpus.__version__ == version
    assert version not in (_PACKAGE / "src/seanchai_corpus/__init__.py").read_text()


def test_only_the_library_knows_of_the_other_package(dist):
    assert _requirements(_wheel(dist, "seanchai_corpus")) == []

    optional = [
        requirement
        for requirement in _requirements(_wheel(dist, "seanchai"))
        if requirement.startswith("seanchai-corpus")
    ]
    assert len(optional) == 1
    assert "extra == 'corpus'" in optional[0]


def test_the_wheels_work_installed(dist, tmp_path):
    bin_dir = _venv(
        tmp_path / "both", _wheel(dist, "seanchai"), _wheel(dist, "seanchai_corpus")
    )

    smoke = subprocess.run(
        [bin_dir / "python", "-I", _SMOKE],
        cwd=tmp_path,
        env=_clean_environment(),
        capture_output=True,
        text=True,
    )
    assert smoke.returncode == 0, smoke.stderr
    assert seanchai_corpus.__version__ in smoke.stdout

    source = _CORPUS_DIR / "rfc" / "rfc6733.dad"
    lint = subprocess.run(
        [bin_dir / "seanchai", "lint", source],
        cwd=tmp_path,
        env=_clean_environment(),
        capture_output=True,
        text=True,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr


def test_the_library_wheel_works_without_the_corpus(dist, tmp_path):
    bin_dir = _venv(tmp_path / "alone", _wheel(dist, "seanchai"))
    source = tmp_path / "file.dad"
    shutil.copy(_CORPUS_DIR / "rfc" / "rfc6733.dad", source)

    refused = subprocess.run(
        [
            bin_dir / "python",
            "-I",
            "-c",
            "from seanchai import corpus\n"
            "try:\n"
            "    corpus.Corpus.installed()\n"
            "except corpus.CorpusNotInstalledError as error:\n"
            "    print(error)\n",
        ],
        cwd=tmp_path,
        env=_clean_environment(),
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 0, refused.stderr
    assert "seanchai-corpus" in refused.stdout

    lint = subprocess.run(
        [bin_dir / "seanchai", "lint", source],
        cwd=tmp_path,
        env=_clean_environment(),
        capture_output=True,
        text=True,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
