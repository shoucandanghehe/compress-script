from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from compress_script.logger import console


def get_progress() -> Progress:
    return Progress(
        TextColumn('[bold blue]{task.fields[task_name]}', justify='right'),
        TextColumn('[bold green]{task.fields[status]}'),
        BarColumn(bar_width=None),
        '[progress.percentage]{task.percentage:>3.1f}%',
        '•',
        DownloadColumn(binary_units=True),
        '•',
        TransferSpeedColumn(),
        '•',
        TimeRemainingColumn(),
        console=console,
    )


def get_total() -> Progress:
    return Progress(
        TextColumn('[bold green]{task.description}'),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        '•',
        TimeElapsedColumn(),
        console=console,
    )
