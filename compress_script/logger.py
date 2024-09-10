from loguru import logger
from rich.console import Console
from richuru import install  # type: ignore[import-untyped]

console = Console()

install(rich_console=console)

__all__ = ['logger']
