import asyncio

from job_copilot.config import get_settings
from job_copilot.database import Database


async def main() -> None:
    await Database(get_settings().database_url).migrate()


if __name__ == "__main__":
    asyncio.run(main())

