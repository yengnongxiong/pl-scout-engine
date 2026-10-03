"""Analytical SQL (CTEs + window functions), portable across SQLite and Postgres."""

# Note: SQLAlchemy ``text()`` treats ``:name`` as a bind parameter even inside SQL
# comments, so comments in these files name parameters without the leading colon.
