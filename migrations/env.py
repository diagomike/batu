"""Alembic environment: the database and the table definitions come from app/database.py."""
from alembic import context

from app import database

config = context.config
target_metadata = database.metadata


def run_migrations_offline():
    context.configure(url=database.url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    conn = config.attributes.get("connection")
    if conn is not None:  # called from app.database.migrate()
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with database.engine().connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
