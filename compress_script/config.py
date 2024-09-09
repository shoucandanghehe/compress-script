from pathlib import Path
from shutil import rmtree
from sys import argv
from typing import Self

from msgspec import Struct, toml


class CompressScript(Struct):
    password: str
    save_path: str
    illegal_chars: dict[str, str]

    @classmethod
    def default(cls) -> Self:
        return cls(
            password='Modify this',  # noqa: S106
            save_path='Modify this',
            illegal_chars={
                '\\': '＼',  # noqa: RUF001
                '/': '／',  # noqa: RUF001
                ':': '：',  # noqa: RUF001
                '*': '＊',  # noqa: RUF001
                '?': '？',  # noqa: RUF001
                '"': '＂',  # noqa: RUF001
                '<': '＜',  # noqa: RUF001
                '>': '＞',  # noqa: RUF001
                '|': '｜',  # noqa: RUF001
            },
        )


class ConfigModel(Struct):
    compress_script: CompressScript

    @classmethod
    def default(cls) -> Self:
        return cls(compress_script=CompressScript.default())


class Config:
    def __init__(self, path: Path | None = None):
        if path is None:
            path = Path(argv[0]).parent / 'config.toml'
        self.path = path
        if self.path.exists() and self.path.is_file():
            self.config = self.load(self.path)
        else:
            rmtree(self.path) if self.path.is_dir() else self.path.unlink(missing_ok=True)
            self.path.touch()
            self.config = self.set_default()

    @staticmethod
    def load(path: Path) -> ConfigModel:
        return toml.decode(path.read_text(encoding='utf-8'), type=ConfigModel)

    def set_default(self) -> ConfigModel:
        self.path.write_bytes(toml.encode(config := ConfigModel.default()))
        return config

    @property
    def password(self) -> str:
        return self.config.compress_script.password

    @property
    def save_path(self) -> Path:
        return Path(self.config.compress_script.save_path)

    @property
    def illegal_chars(self) -> dict[str, str]:
        return self.config.compress_script.illegal_chars
