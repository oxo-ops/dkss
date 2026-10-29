"""Q04 adapter; credentials, approval and evidence belong to migration_entry."""
from dkss_app import master_generations


def apply(*, engine, schema, target_guard):
    if not isinstance(schema, str) or not schema or not callable(target_guard):
        raise ValueError('Explicit schema and target guard are required')
    return master_generations.upgrade_storage(
        engine, schema, target_guard=target_guard)
