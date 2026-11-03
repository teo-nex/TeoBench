"""Run inside the OS sandbox. Only inputs, never expected outputs, enter here."""

import ast
import json
import resource
import sys

resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
if sys.platform.startswith('linux'):
    resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))


def execute(source, inputs):
    tree = ast.parse(source)
    if not any(isinstance(node, ast.FunctionDef) and node.name == "solve" for node in tree.body):
        raise ValueError("missing_solve")
    banned = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Global, ast.Nonlocal,
              ast.AsyncFunctionDef, ast.Await, ast.With, ast.AsyncWith)
    for node in ast.walk(tree):
        if isinstance(node, banned):
            raise ValueError("forbidden_syntax")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("forbidden_name")
        if isinstance(node, ast.Attribute) and node.attr.startswith(("_", "gi_", "cr_", "ag_", "f_", "tb_")):
            raise ValueError("forbidden_attribute")
        if isinstance(node, (ast.FunctionDef, ast.Lambda)) and getattr(node, "decorator_list", []):
            raise ValueError("forbidden_decorator")
    names = ["bin", "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "frozenset",
             "int", "isinstance", "len", "list", "map", "max", "min", "next", "range", "reversed",
             "round", "set", "sorted", "str", "sum", "tuple", "zip", "ValueError", "Exception"]
    safe = {name: getattr(__builtins__, name) for name in names}
    scope = {"__builtins__": safe}
    exec(compile(tree, "<submission>", "exec"), scope)
    return [scope["solve"](item) for item in inputs]


try:
    request = json.load(sys.stdin)
    result = execute(request["source"], request["inputs"])
    payload = json.dumps({"outputs": result}, allow_nan=False)
    if len(payload) > 2_000_000:
        raise ValueError('worker_output_limit')
    print(payload)
except Exception as error:
    print(json.dumps({"error": type(error).__name__}))
