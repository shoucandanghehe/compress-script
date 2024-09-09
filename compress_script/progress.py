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

progress = Progress(
    TextColumn('[bold green]{task.fields[status]}'),
    TextColumn('[bold blue]{task.fields[filename]}', justify='right'),
    BarColumn(bar_width=None),
    '[progress.percentage]{task.percentage:>3.1f}%',
    '•',
    DownloadColumn(binary_units=True),
    '•',
    TransferSpeedColumn(),
    '•',
    TimeRemainingColumn(),
)

total = Progress(
    TextColumn('[bold green]{task.description}'),
    BarColumn(bar_width=None),
    MofNCompleteColumn(),
    '•',
    TimeElapsedColumn(),
)
