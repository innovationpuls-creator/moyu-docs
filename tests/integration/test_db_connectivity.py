import pytest
from app_infra.postgres.engine import get_db_session
from sqlalchemy import text


@pytest.mark.asyncio
async def test_database_connection():
    async with get_db_session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
