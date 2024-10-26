from loguru import logger
from rich.console import Console
from rich.theme import Theme
from richuru import install  # type: ignore[import-untyped]

console = Console(
    theme=Theme(
        {
            'logging.level.success': 'green',
            'logging.level.trace': 'bright_black',
        }
    )
)

install(rich_console=console)

__all__ = ['logger']
