"""Static checks that a SQL string is a single read-only query.

This is defense in depth: the server also runs every query in a READ ONLY transaction
as the pms_readonly role, which only has SELECT privileges.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Copy, exp.Into, exp.Lock, exp.Set, exp.Transaction,
    exp.Commit, exp.Rollback, exp.Grant, exp.Revoke, exp.Use, exp.Analyze,
)

# Functions that sleep, touch the server filesystem, change settings, signal other
# backends or execute SQL passed in as a string.
FORBIDDEN_FUNCTIONS = {
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "lo_get", "lo_open",
    "dblink", "dblink_exec", "dblink_connect",
    "set_config", "pg_reload_conf", "pg_terminate_backend", "pg_cancel_backend",
    "pg_advisory_lock", "pg_advisory_xact_lock", "pg_try_advisory_lock",
    "query_to_xml", "query_to_xml_and_xmlschema", "query_to_xmlschema",
    "cursor_to_xml", "cursor_to_xmlschema",
}


class UnsafeQueryError(ValueError):
    pass


def check_read_only(sql: str) -> None:
    """Raise UnsafeQueryError unless `sql` is exactly one SELECT / WITH ... SELECT query."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as e:
        raise UnsafeQueryError(f"Could not parse SQL: {e}") from e
    if len(statements) != 1:
        raise UnsafeQueryError(f"Expected exactly one statement, got {len(statements)}.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeQueryError("Only SELECT queries (optionally with WITH) are allowed.")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(f"{node.key.upper()} is not allowed; queries must be read-only.")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in FORBIDDEN_FUNCTIONS:
                raise UnsafeQueryError(f"Function {name}() is not allowed.")
