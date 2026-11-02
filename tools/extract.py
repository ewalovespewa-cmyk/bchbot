import ast, json, re, sys
FILES = ["handlers/menu.py","handlers/common.py","handlers/expedition.py","handlers/phases.py","handlers/photohunt.py",
         "handlers/bingo.py","handlers/admin.py","handlers/diagnostics.py","chatutil.py","integration/gate.py","handlers/phase3.py"]
CYR = re.compile("[а-яА-ЯёЁ]")
out = []
def render(node):
    if isinstance(node, ast.Constant): return node.value
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant): parts.append(v.value)
        else:
            src = ast.unparse(v.value)
            parts.append("{" + src + "}")
    return "".join(parts)
for f in FILES:
    tree = ast.parse(open(f, encoding="utf-8").read())
    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p): parents[c] = p
    def func_of(n):
        while n in parents:
            n = parents[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): return n.name
        return "(модуль)"
    def skip(n):
        p = parents.get(n)
        # docstring
        if isinstance(p, ast.Expr): return True
        # inside JoinedStr handled by parent
        if isinstance(p, ast.JoinedStr): return True
        q = n
        while q in parents:
            q = parents[q]
            if isinstance(q, ast.Call):
                fn = ast.unparse(q.func)
                if fn.startswith("log.") or fn.startswith("logging.") or fn in ("RuntimeError",): return True
        return False
    for n in ast.walk(tree):
        if isinstance(n, (ast.Constant, ast.JoinedStr)):
            if isinstance(n, ast.Constant) and not isinstance(n.value, str): continue
            if skip(n): continue
            t = render(n)
            if not CYR.search(t): continue
            out.append({"file": f, "line": n.lineno, "func": func_of(n), "text": t})
out.sort(key=lambda r: (r["file"], r["line"]))
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(len(out))
from collections import Counter
print(Counter(r["file"] for r in out))
