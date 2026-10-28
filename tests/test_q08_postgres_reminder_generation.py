"""Reminder assignment tests on an explicitly selected disposable PostgreSQL."""
import test_q08_reminder_generation as reminder
from test_q08_postgres_identity import DisposablePostgres


class PostgresReminderGenerationTests(DisposablePostgres, reminder.ReminderGenerationTests):
    pass
