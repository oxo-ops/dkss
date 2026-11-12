"""Dependency-free contract: only authored constants can reach error responses."""
import ast
from pathlib import Path
import unittest


class PriorityConfirmationErrorMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / 'dkss_app' / 'priority_confirmations.py'
        cls.tree = ast.parse(cls.path.read_text(encoding='utf-8'))
        nodes = [node for node in cls.tree.body
                 if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_PUBLIC_VALIDATION_MESSAGES' for t in node.targets))
                 or (isinstance(node, ast.FunctionDef) and node.name == '_public_validation_message')]
        namespace = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(cls.path), 'exec'), namespace)
        cls.public = staticmethod(namespace['_public_validation_message'])
        cls.messages = namespace['_PUBLIC_VALIDATION_MESSAGES']

    def test_all_deliberate_reasons_remain_available(self):
        self.assertEqual(len(set(self.messages)), len(self.messages))
        for message in self.messages:
            with self.subTest(message=message):
                self.assertEqual(self.public(ValueError(message), 'fallback'), message)

    def test_internal_types_and_unknown_value_errors_are_not_disclosed(self):
        private = 'SYNTHETIC_PRIVATE database-url /internal/file.py SELECT secret'
        for kind in (ValueError, TypeError, KeyError, ImportError):
            self.assertEqual(self.public(kind(private), 'fallback'), 'fallback')
        for value in ('', self.messages[0] + private, private + self.messages[0]):
            self.assertEqual(self.public(ValueError(value), 'fallback'), 'fallback')
        self.assertEqual(self.public(ValueError(self.messages[0], private), 'fallback'), 'fallback')

    def test_no_exception_stringification_or_custom_argument_equality(self):
        class HostileError(ValueError):
            def __str__(self):
                raise AssertionError('Do not stringify exceptions')
        class HostileString(str):
            def __eq__(self, other):
                raise AssertionError('Do not invoke supplied equality')
        self.assertEqual(self.public(HostileError('private'), 'fallback'), 'fallback')
        self.assertEqual(self.public(ValueError(HostileString(self.messages[0])), 'fallback'), 'fallback')

    def test_error_responses_use_constant_selection(self):
        routes = {'priority_confirmation_data', 'preview_priority_confirmation', 'save_priority_confirmation'}
        helpers = []
        for function in self.tree.body:
            if not isinstance(function, ast.FunctionDef) or function.name not in routes:
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertFalse(node.func.id == 'str' and any(isinstance(arg, ast.Name) and arg.id == 'error' for arg in node.args))
                    if node.func.id == '_public_validation_message':
                        self.assertIsInstance(node.args[1], ast.Constant)
                        helpers.append(function.name)
        self.assertEqual(set(helpers), routes)
