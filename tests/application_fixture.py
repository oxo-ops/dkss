"""Compatibility adapter for existing assertions and mocks during package migration.

Attribute reads and patches resolve to the actual defining module. Production
request code never accesses this adapter. No assertions or input cases change.
"""
from dkss_app.compat import owner_module, resolve


class ApplicationFixture:
    def __init__(self, app):
        from master_form_fixture import FreshMasterFormsClient
        from identity_fixture import PersonSelectionClient
        class SignedFormClient(FreshMasterFormsClient, PersonSelectionClient):
            """Compose existing test adapters; preserve explicitly supplied proofs."""
            pass
        app.test_client_class = SignedFormClient
        object.__setattr__(self, "app", app)

    def __getattr__(self, name):
        return resolve(name, self.app)

    def __setattr__(self, name, value):
        setattr(owner_module(name), name, value)

    def __delattr__(self, name):
        delattr(owner_module(name), name)
