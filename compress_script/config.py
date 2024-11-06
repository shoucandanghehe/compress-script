import sys
from pathlib import Path
from shutil import rmtree
from sys import argv
from typing import Generic, NoReturn, Self, TypeVar, override

from msgspec import Struct, ValidationError, toml

from .logger import logger

# ruff: noqa: RUF001


class CompressScriptV1(Struct):
    password: str
    save_path: str
    illegal_chars: dict[str, str]

    @classmethod
    def default(cls) -> Self:
        return cls(
            password='Modify this',  # noqa: S106
            save_path='Modify this',
            illegal_chars={
                '\\': '＼',
                '/': '／',
                ':': '：',
                '*': '＊',
                '?': '？',
                '"': '＂',
                '<': '＜',
                '>': '＞',
                '|': '｜',
            },
        )


class Archive(Struct):
    enabled: bool
    save_path: str


class CompressScriptV2(Struct):
    password: str
    archive: Archive
    illegal_chars: dict[str, str]

    @classmethod
    def default(cls) -> Self:
        return cls(
            password='Modify this',  # noqa: S106
            archive=Archive(enabled=False, save_path='Modify this'),
            illegal_chars={
                '\\': '＼',
                '/': '／',
                ':': '：',
                '*': '＊',
                '?': '？',
                '"': '＂',
                '<': '＜',
                '>': '＞',
                '|': '｜',
            },
        )


T = TypeVar('T', bound='BaseConfig')


# this class should be abstract, but msgspec doesn't support metaclass
class BaseConfig(Struct, Generic[T]):
    @staticmethod
    # @abstractmethod
    def previous() -> type[T] | None:
        raise NotImplementedError

    @classmethod
    # @abstractmethod
    def from_previous(cls, config: T) -> Self:
        raise NotImplementedError

    @classmethod
    def load_or_update(cls, path: Path) -> Self:
        try:
            return toml.decode(path.read_text(encoding='utf-8'), type=cls)
        except ValidationError:
            if (previous := cls.previous()) is None:
                raise
            ret = cls.from_previous(previous.load_or_update(path))
            path.write_bytes(toml.encode(ret))
            return ret


class ConfigModelV1(BaseConfig):
    compress_script: CompressScriptV1

    @override
    @staticmethod
    def previous() -> None:
        return None

    @override
    @classmethod
    def from_previous(cls, config: BaseConfig) -> Self:
        raise NotImplementedError

    @classmethod
    def default(cls) -> Self:
        return cls(compress_script=CompressScriptV1.default())


class ConfigModelV2(BaseConfig[ConfigModelV1]):
    compress_script: CompressScriptV2

    @override
    @staticmethod
    def previous() -> type[ConfigModelV1] | None:
        return ConfigModelV1

    @override
    @classmethod
    def from_previous(cls, config: ConfigModelV1) -> Self:
        return cls(
            compress_script=CompressScriptV2(
                password=config.compress_script.password,
                archive=Archive(enabled=False, save_path=config.compress_script.save_path),
                illegal_chars=config.compress_script.illegal_chars,
            )
        )

    @classmethod
    def default(cls) -> Self:
        return cls(compress_script=CompressScriptV2.default())


LastConfig = ConfigModelV2


class Config:
    def __init__(self, path: Path | None = None):
        if path is None:
            path = Path(argv[0]).parent / 'config.toml'
        self.path = path
        if self.path.exists() and self.path.is_file():
            try:
                self.config = LastConfig.load_or_update(self.path)
            except ValidationError:
                pass
            else:
                return
        rmtree(self.path) if self.path.is_dir() else self.path.unlink(missing_ok=True)
        self.path.touch()
        self.set_default()

    def set_default(self) -> NoReturn:
        self.path.write_bytes(toml.encode(config := LastConfig.default()))
        self.config = config
        logger.success(f'已生成默认配置文件: {self.path}')
        logger.warning('请修改配置文件后重新运行程序')
        sys.exit(0)

    @property
    def password(self) -> str:
        return self.config.compress_script.password

    @property
    def archive_enabled(self) -> bool:
        return self.config.compress_script.archive.enabled

    @property
    def save_path(self) -> Path:
        return Path(self.config.compress_script.archive.save_path)

    @property
    def illegal_chars(self) -> dict[str, str]:
        return self.config.compress_script.illegal_chars
