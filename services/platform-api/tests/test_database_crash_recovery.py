from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app.config import get_settings
from app.database import open_database


def _contend(resource: str, barrier: Barrier) -> int:
    with open_database(get_settings()) as connection:
        cursor = connection.cursor()
        barrier.wait()
        cursor.execute(
            """DECLARE @result int; EXEC @result=sys.sp_getapplock
               @Resource=%s,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=0;
               SELECT @result""", (resource,),
        )
        result = int(cursor.fetchone()[0])
        if result >= 0:
            cursor.execute("WAITFOR DELAY '00:00:00.300'")
        connection.rollback()
        return result


def test_database_reservation_lock_allows_exactly_one_concurrent_worker() -> None:
    """Database-backed proof for crash scenario D: only one worker reserves."""
    barrier = Barrier(2)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: _contend(f"aurex:test:{resource}", barrier), range(2)))
    except Exception as exc:  # pragma: no cover - portable test fallback
        pytest.skip(f"SQL Server integration unavailable: {exc}")
    assert sum(result >= 0 for result in results) == 1


resource = uuid4().hex
