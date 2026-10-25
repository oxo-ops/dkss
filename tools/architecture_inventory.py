"""Emit a static Python inventory as JSON without importing the app or using its DB.

Run: python tools/architecture_inventory.py > inventory.json
Definitions/imports are static evidence, not a runtime call graph.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE_METHODS = {"route", "get", "post", "put", "patch", "delete"}


def inspect_module(path, local_modules):
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    definitions, routes, top_level_calls = [], [], []
    imports, namespace_keys = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "app"
                    and decorator.func.attr in ROUTE_METHODS):
                    routes.append({"function": node.name, "line": decorator.lineno,
                                   "rule": ast.unparse(decorator.args[0]) if decorator.args else "",
                                   "decorator": decorator.func.attr})
        elif (isinstance(node, ast.Subscript)
              and isinstance(node.value, ast.Name) and node.value.id == "g"
              and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            namespace_keys.add(node.slice.value)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            is_class = isinstance(node, ast.ClassDef)
            definitions.append({
                "name": node.name, "kind": "class" if is_class else "function",
                "line": node.lineno, "end_line": node.end_lineno,
                "lines": node.end_lineno - node.lineno + 1,
                "db_model": is_class and any(ast.unparse(base) == "db.Model" for base in node.bases),
            })
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            top_level_calls.append({"line": node.lineno, "call": ast.unparse(node.value.func)})
        elif isinstance(node, ast.With):
            top_level_calls.append({"line": node.lineno, "call": "with " + ", ".join(
                ast.unparse(item.context_expr) for item in node.items)})
    return {
        "path": path.relative_to(ROOT).as_posix(), "lines": len(source.splitlines()),
        "top_level_functions": sum(d["kind"] == "function" for d in definitions),
        "top_level_classes": sum(d["kind"] == "class" for d in definitions),
        "direct_db_models": sum(d["db_model"] for d in definitions),
        "route_decorators": len(routes), "routes": routes,
        "local_imports": sorted(imports & local_modules),
        "namespace_keys": sorted(namespace_keys),
        "globals_calls": [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
                          and isinstance(n.func, ast.Name) and n.func.id == "globals"],
        "top_level_calls": top_level_calls, "definitions": definitions,
    }


def inventory():
    files = sorted(ROOT.glob("*.py"))
    local_modules = {p.stem for p in files}
    modules = [inspect_module(path, local_modules) for path in files]
    tests = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        count = sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                    for n in ast.walk(tree))
        tests.append({"path": path.relative_to(ROOT).as_posix(), "defined_test_methods": count})
    return {"modules": modules, "tests": tests,
            "workflows": [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / ".github/workflows").glob("*.yml"))]}


if __name__ == "__main__":
    print(json.dumps(inventory(), ensure_ascii=False, indent=2))
