from asyncio import Lock as ALock
from asyncio import create_subprocess_shell, create_task, gather, run, sleep
from asyncio.exceptions import IncompleteReadError
from asyncio.subprocess import PIPE, Process
from collections.abc import AsyncGenerator
from hashlib import sha256
from os import startfile
from pathlib import Path
from re import search
from sys import argv
from time import time
from typing import Literal, NamedTuple

from aiofiles import open as aiopen
from aiofiles.threadpool.binary import AsyncBufferedReader
from aioshutil import move
from pytimedinput import timedInput  # type: ignore[import-untyped]
from rich.console import Group
from rich.live import Live
from rich.progress import TaskID

from compress_script.config import Config
from compress_script.exception import CanNotFindProductsError, ProgressParsingError
from compress_script.lock import Lock
from compress_script.logger import logger
from compress_script.progress import progress, total

CONFIG = Config()


def get_total_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
    return 0


async def call_compression(source_path: Path, file_name: str) -> Process:
    logger.info('调用 7zip 进行压缩')
    cmd = f'7z a -t7z -m0=FLZMA2 -mmt=on -mx9 -md=64m -mfb=64 -ms=on -mqs=on -sccUTF-8 "-p{CONFIG.password}" -mhe=on -bb0 -bso0 -bsp1 -v1610612736 -mtc=on -mta=on "{source_path.parent/file_name}.7z" "{source_path}"'
    return await create_subprocess_shell(cmd, stdout=PIPE)


async def call_test(file_path: Path) -> Process:
    logger.info('调用 7zip 进行测试')
    cmd = f'7z t -sccUTF-8 "-p{CONFIG.password}" -bso0 -bsp1 "{file_path}"'
    return await create_subprocess_shell(cmd, stdout=PIPE)


class CompressProgress(NamedTuple):
    rate: int
    file: str


class TestProgress(NamedTuple):
    rate: int
    status: Literal['Scan', 'Open', 'Unknown', 'Test']
    file: str | None


async def parsing_progress(process: Process) -> AsyncGenerator[str]:
    logger.debug('开始解析 7zip 运行进度')
    if process.stdout is not None:
        try:
            while True:
                yield (await process.stdout.readuntil(b'\r')).decode().lstrip()
        except IncompleteReadError:
            pass
    else:
        raise ProgressParsingError


async def parsing_compress(process: Process) -> AsyncGenerator[CompressProgress]:
    async for line in parsing_progress(process):
        if (result := search(r'(\d+)% \d+ \+ (.*)\r', line)) is not None:
            yield CompressProgress(rate=int(result.group(1)), file=result.group(2).strip().rsplit(maxsplit=1)[-1])


async def parsing_test(process: Process) -> AsyncGenerator[TestProgress]:
    async for line in parsing_progress(process):
        if (result := search(r'(\d+)% T (.*)\r', line)) is not None:
            yield TestProgress(rate=int(result.group(1)), status='Test', file=result.group(2))
            continue
        if (result := search(r'(\d+)M Scan\r', line)) is not None:
            yield TestProgress(rate=int(result.group(1)), status='Scan', file=None)
            continue
        if (result := search(r'(\d+)% 1 Open\r', line)) is not None:
            yield TestProgress(rate=int(result.group(1)), status='Open', file=None)
            continue
        if (result := search(r'(\d+)%', line)) is not None:
            yield TestProgress(rate=int(result.group(1)), status='Unknown', file=None)
            continue


def handle_products(source_path: Path, file_name: str) -> list[Path]:
    # 查找压缩产物是否只有一个 .7z.001 文件 如果是 则将 .7z.001 改成 .7z
    logger.info('获取产物列表')
    product_list: list[Path] = [
        i
        for i in source_path.parent.iterdir()
        if i.name.split('.')[0] == file_name
        and '.7z' in i.suffixes
        and '.old' not in i.suffixes
        and i.suffix[1:].isdigit()
    ]
    match len(product_list):
        case 0:
            raise CanNotFindProductsError
        case 1:  # 只有一个 .7z.001 文件
            logger.debug('只找到一个分卷, 重命名为 .7z')
            product_list[0] = product_list[0].rename(product_list[0].stem)
    return product_list


def rename_conflict(find_path: Path, file_name: str) -> None:
    logger.info('重命名可能导致冲突的文件')
    for i in find_path.iterdir():
        if i.name.split('.')[0] == file_name and '.7z' in i.suffixes:
            new_i = i.rename(f'{i}.old')
            logger.success(f'{i} 👉 {new_i}')


async def read_file(file: AsyncBufferedReader, size: int) -> AsyncGenerator[bytes]:
    while True:
        data = await file.read(size)
        if not data:
            break
        yield data


async def calculate_hash(file_list: list[Path]) -> list[Path]:
    logger.info('开始计算Hash')
    lock = ALock()
    with Live(Group(progress, total)):

        async def worker(file: Path, task_id: TaskID) -> Path:
            progress.start_task(task_id)
            async with lock:
                progress.update(task_id, status='Hashing...')
                hasher = sha256()
                async with aiopen(file, mode='rb') as f:
                    async for i in read_file(f, 1024 * 1024):
                        hasher.update(i)
                        progress.update(task_id, advance=len(i))
            progress.update(task_id, status='Completed')
            hash_file = Path(f'{file.name}.sha256')
            hash_file.write_text(hasher.hexdigest())
            return hash_file

        tasks = [
            create_task(
                worker(
                    i,
                    progress.add_task(
                        description='hash',
                        status='Waiting...',
                        filename=i.name,
                        total=i.stat().st_size,
                        start=False,
                    ),
                )
            )
            for i in file_list
        ]
        task_id = total.add_task(description='Hash总进度', total=len(tasks))
        for task in tasks:
            task.add_done_callback(lambda _: total.update(task_id, advance=1))
        return await gather(*tasks)


async def archive_to_folder(file_list: list[Path], source_path: Path, archive_name: str) -> None:
    logger.info('开始归档')
    logger.info('重命名源文件')
    while True:
        try:
            source_path = source_path.rename(f'{source_path}-已压缩')
        except PermissionError:
            timedInput(prompt=f'请检查 {source_path} 是否被占用 (3s)', timeout=3)
        else:
            break
    archive_path = source_path.parent / archive_name
    logger.info('创建存储文件夹')
    archive_path.mkdir(parents=True, exist_ok=True)
    logger.info('移动文件到存储文件夹')
    for i in file_list:
        await move(i, archive_path)
        logger.debug(f'移动 {i} 到存储文件夹')
    logger.info('移动存储文件夹到归档文件夹')
    await move(archive_path, CONFIG.save_path)


async def _main(source_path: Path) -> None:
    logger.info(f'开始处理 {source_path}')
    file_name = await input_custom() or source_path.stem

    # 重命名可能存在冲突的文件
    rename_conflict(source_path.parent, file_name)

    # 开始压缩
    process = await call_compression(source_path, file_name)
    with progress as p:
        task_id = progress.add_task(
            'compress',
            status='Compressing...',
            filename=source_path.name,
            total=(total := get_total_size(source_path)),
        )
        async for i in parsing_compress(process):
            p.update(task_id, completed=total * (i.rate / 100), status=f'Compressing {i.file}')
        p.update(task_id, completed=total, status='Completed', refresh=True)

    # 处理产物
    product_list = handle_products(source_path, file_name)

    # 开始测试
    process = await call_test(next((i for i in product_list if i.suffix == '.001'), product_list[0]))
    with progress as p:
        task_id = progress.add_task(
            'compress',
            status='Testing...',
            filename=source_path.name,
            total=(total := get_total_size(source_path)),
        )
        async for i in parsing_test(process):
            match i.status:
                case 'Test':
                    p.update(
                        task_id,
                        completed=total * (i.rate / 100),
                        status=f'Testing {i.file}' if i.file is not None else 'Testing...',
                    )
                case 'Open':
                    p.update(
                        task_id,
                        completed=total * (i.rate / 100),
                        status='Opening...',
                    )
                case 'Scan':
                    p.update(
                        task_id,
                        completed=i.rate * 1048576,
                        status='Scanning...',
                    )
                case 'Unknown':
                    p.update(task_id, completed=total * (i.rate / 100))
        p.update(task_id, completed=total, status='Completed', refresh=True)

    # 计算hash
    all_product = product_list + await calculate_hash(product_list)

    # 归档
    await archive_to_folder(all_product, source_path, file_name)


async def input_custom() -> str | None:
    """获取自定义文件名"""
    custom_file_name = timedInput(
        prompt='是否自定义压缩文件名(Y/N): ',
        timeout=3,
        maxLength=1,
        allowCharacters='YNyn',
    )
    if custom_file_name[0].upper() == 'Y':
        file_name = input('请输入自定义文件名: ')
        logger.info('替换非法字符')
        for key, value in CONFIG.illegal_chars.items():
            file_name = file_name.replace(key, value)
        logger.success(f'👉 {file_name}')
        return file_name
    return None


async def explorer() -> None:
    lock = Lock(Path(argv[2]))
    task = await lock.check_swap()
    while True:
        logger.info('获取任务')
        if (source_path := lock.get_path()) is None:
            logger.warning('待压缩队列为空, 开始等待超时')
            timeout = int(time()) + 3
            while int(time()) < timeout:
                if (source_path := lock.get_path()) is None:
                    await sleep(0)
                    continue
                break
            else:
                logger.success('没有获取到新的压缩任务, 进程结束')
                break
        await _main(source_path)
        logger.success(f'{source_path} 处理完成')
    logger.debug('开始清理')
    logger.debug('结束 swap_loop')
    task.cancel()


async def manual() -> None:
    for path in [Path(i) for i in argv[1:]]:
        await _main(path)


async def main() -> None:
    if len(argv) > 1:
        if argv[1] == 'explorer':
            logger.info('右键菜单运行')
            await explorer()
        else:
            logger.info('手动运行')
            await manual()
        logger.info('打开归档文件夹')
        startfile(CONFIG.save_path)  # noqa: S606
    else:
        logger.success('没有输入参数, 正在退出')


if __name__ == '__main__':
    run(main())
