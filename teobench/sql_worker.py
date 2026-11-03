"""Trusted read-only SQL runner; receives fixtures without expected answers."""
import json
import resource
import sqlite3
import sys

resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
if sys.platform.startswith('linux'):
    resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))


def execute(query, fixture):
    if len(query.encode("utf-8")) > 100_000:
        raise ValueError("sql_length_limit")
    connection = sqlite3.connect(":memory:")
    try:
        # This is a dedicated sandboxed process: the SQLite-wide heap ceiling
        # cannot change the embedding agent's database connections.
        ceiling = connection.execute('PRAGMA hard_heap_limit=67108864').fetchone()
        if not ceiling or not 0 < ceiling[0] <= 67108864:
            raise RuntimeError('OS_sandbox_unavailable_sqlite_heap_limit_required')
        if hasattr(connection, 'setlimit'):
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
            connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 100)
            connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
        for table, info in fixture["tables"].items():
            columns = ",".join('"'+c+'"' for c in info["columns"])
            connection.execute('CREATE TABLE "'+table+'" ('+columns+')')
            connection.executemany('INSERT INTO "'+table+'" VALUES ('+','.join('?' for _ in info["columns"])+')', info["rows"])
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

        def authorize(action, arg1, arg2, database, trigger):
            if action not in allowed or (action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() == "load_extension"):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        steps = 0

        def progress():
            nonlocal steps
            steps += 1
            return steps > 500

        connection.set_progress_handler(progress, 1000)
        if hasattr(connection, "setlimit"):
            connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 100_000)
        cursor = connection.execute(query)
        rows = []
        size = 0
        for row in cursor:
            if len(rows) >= 10_000:
                raise ValueError('row_limit')
            size += len(json.dumps(list(row), ensure_ascii=True, allow_nan=False))
            if size > 1_000_000:
                raise ValueError('sql_output_limit')
            rows.append(list(row))
        return rows
    finally:
        connection.close()


try:
    request = json.load(sys.stdin)
    outputs = [execute(request['query'], fixture) for fixture in request['fixtures']]
    payload = json.dumps({'outputs': outputs}, allow_nan=False)
    if len(payload) > 2_000_000:
        raise ValueError('sql_output_limit')
    print(payload)
except Exception as error:
    print(json.dumps({'error': type(error).__name__, 'message': str(error)[:150]}))
