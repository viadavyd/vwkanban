import pytest
from sqlalchemy import text


@pytest.fixture(autouse=True)
async def clean_db(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users CASCADE"))
