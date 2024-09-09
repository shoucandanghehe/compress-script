from asyncio import Task, get_event_loop, sleep
from atexit import register
from os import getpid
from pathlib import Path
from sys import argv, exit
from time import time
from typing import NoReturn

from aiofiles import open as aiopen
from filelock import FileLock, Timeout
from msgspec import DecodeError, Struct, json

from .logger import logger


class Swap(Struct):
    main_pid: int
    swap: dict[int, str]
    last_update: int


decoder = json.Decoder(type=Swap)
encoder = json.Encoder()


class Lock:
    LOCK_FILE = Path(Path(argv[0]).parent / 'compress_script.json.lock')
    SWAP_FILE = Path(LOCK_FILE.parent / LOCK_FILE.stem)
    LOCK = FileLock(LOCK_FILE)
    waiting_list: set[Path]

    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self.waiting_list = {source_path}

    async def check_swap(self) -> Task:
        logger.info('开始检查 swap')
        with self.LOCK:
            try:
                content = await self.read_swap()
                if (last_update := content.last_update) is None or (int(time()) - last_update) > 60 * 60 * 24:
                    logger.debug('swap 不存在, 或者超时')
                    content = await self.init_swap()
            except (DecodeError, FileNotFoundError, AssertionError):
                logger.debug('swap 异常')
                content = await self.init_swap()
            # 如果主进程不是自己, 将Path传递给主进程
            if (main_pid := content.main_pid) != getpid():
                logger.info(f'主进程为: {main_pid}')
                await self.send_file()
        # 如果主进程是自己, 启用Loop
        if main_pid == getpid():
            logger.debug('注册退出清理函数')
            register(self.clear)
            loop = get_event_loop()
            return loop.create_task(self.swap_loop())
        logger.success('Done')
        exit()

    async def send_file(self) -> None:
        logger.info('将待压缩路径传递给主进程')
        content = await self.read_swap()
        content.swap.update({getpid(): str(self.source_path.absolute())})
        self.waiting_list.remove(self.source_path)
        async with aiopen(self.SWAP_FILE, mode='wb') as file:
            await file.write(encoder.encode(content))

    async def swap_loop(self) -> NoReturn:
        logger.debug('重新设定 LOCK.timeout')
        self.LOCK.timeout = 0.1
        while True:
            try:
                with self.LOCK:
                    content = await self.read_swap()
                    swap = content.swap
                    if len(swap) != 0:
                        for k, v in swap.items():
                            logger.debug(f'收到 PID {k} 传递的路径: {v}')
                            self.waiting_list.add(Path(v))
                        logger.debug('swap 读取完成')
                    await self.init_swap()
            except Timeout:
                logger.debug('Lock 获取超时')
            await sleep(0.1)

    async def read_swap(self) -> Swap:
        logger.debug('读取 swap')
        async with aiopen(self.SWAP_FILE, mode='rb') as file:
            return decoder.decode(await file.read())

    async def init_swap(self) -> Swap:
        logger.debug('刷新 swap')
        async with aiopen(self.SWAP_FILE, mode='wb') as file:
            await file.write(encoder.encode(content := Swap(main_pid=getpid(), swap={}, last_update=int(time()))))
        return content

    def get_path(self) -> Path | None:
        try:
            return self.waiting_list.pop()
        except KeyError:
            return None

    def clear(self) -> None:
        logger.debug('清空 swap')
        with self.LOCK:
            self.SWAP_FILE.write_bytes(b'')
