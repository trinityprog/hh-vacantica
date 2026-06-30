import random
import asyncio


async def pause(min_sec: float = 8, max_sec: float = 25):
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


async def short_pause(min_sec: float = 3, max_sec: float = 8):
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


async def typing_delay():
    await asyncio.sleep(random.uniform(0.05, 0.2))


async def scroll_naturally(page):
    for _ in range(random.randint(2, 5)):
        await page.mouse.wheel(0, random.randint(100, 400))
        await asyncio.sleep(random.uniform(0.3, 1.2))
