"""HELD-OUT benchmark: written BEFORE the false-alarm fixes and never used for tuning.

Same format and matching rules as eval/cases.py, but different defects and different clean decoys,
so it measures whether an improvement generalises rather than memorises the dev set.
"""

from eval.cases import B, case

CASES = [
    # ───────────── buggy ─────────────
    case("h_py_sql_format", "python", "repo.py", '''
def get_orders(cur, customer):
    query = "SELECT * FROM orders WHERE customer = '{}'".format(customer)
    cur.execute(query)
    return cur.fetchall()
''', [B("query = ", "security", "SQL injection via str.format", end="cur.execute")]),

    case("h_py_os_system", "python", "cleanup.py", '''
import os


def remove_dir(path):
    os.system("rm -rf " + path)
''', [B("os.system", "security", "command injection via os.system")]),

    case("h_py_assert_auth", "python", "admin.py", '''
def delete_account(user, account_id, db):
    assert user.is_admin
    db.delete(account_id)
''', [B("assert user.is_admin", "security", "authorization via assert (removed with -O)")]),

    case("h_py_dict_mutation", "python", "prune.py", '''
def drop_empty(data):
    for key in data:
        if not data[key]:
            del data[key]
    return data
''', [B("del data[key]", "bug", "mutating a dict while iterating -> RuntimeError")]),

    case("h_py_late_binding", "python", "hooks.py", '''
def make_handlers():
    return [lambda: i * 2 for i in range(3)]
''', [B("return [lambda", "bug", "late-binding closure: every lambda sees the last i")]),

    case("h_py_jwt_noverify", "python", "token.py", '''
import jwt


def read_claims(token):
    return jwt.decode(token, options={"verify_signature": False})
''', [B("jwt.decode", "security", "JWT signature verification disabled")]),

    case("h_js_proto_pollution", "javascript", "merge.js", '''
function merge(target, source) {
  for (const key in source) {
    if (typeof source[key] === "object") {
      target[key] = merge(target[key] || {}, source[key]);
    } else {
      target[key] = source[key];
    }
  }
  return target;
}
''', [B("target[key] = merge", "security", "prototype pollution via __proto__ keys")]),

    case("h_js_cmd_injection", "javascript", "ls.js", '''
const { exec } = require("child_process");

app.get("/list", (req, res) => {
  exec("ls " + req.query.dir, (err, stdout) => res.send(stdout));
});
''', [B("exec(", "security", "command injection from query parameter")]),

    case("h_js_var_closure", "javascript", "timers.js", '''
function schedule() {
  for (var i = 0; i < 3; i++) {
    setTimeout(() => console.log(i), 100);
  }
}
''', [B("setTimeout", "bug", "var-scoped loop variable: prints 3 three times")]),

    case("h_go_nil_map", "go", "counts.go", '''
package main

func tally(words []string) map[string]int {
	var counts map[string]int
	for _, w := range words {
		counts[w]++
	}
	return counts
}
''', [B("counts[w]++", "bug", "write to nil map panics")]),

    case("h_java_string_eq", "java", "Auth.java", '''
public class Auth {
    public boolean isAdmin(String role) {
        return role == "admin";
    }
}
''', [B('role == "admin"', "bug", "== compares references, not string contents")]),

    case("h_c_buffer_off_by_one", "c", "zero.c", '''
void clear(void) {
    char buf[10];
    for (int i = 0; i <= 10; i++) {
        buf[i] = 0;
    }
}
''', [B("for (int i", "bug", "writes buf[10], one past the end")]),

    # ───────────── clean (incl. decoys) ─────────────
    case("h_clean_py_in_clause", "python", "repo.py", '''
def get_users(cur, ids):
    placeholders = ",".join("?" for _ in ids)
    cur.execute(f"SELECT * FROM users WHERE id IN ({placeholders})", list(ids))
    return cur.fetchall()
''', note="decoy: f-string builds only '?' placeholders; values are bound"),

    case("h_clean_py_lock", "python", "counter.py", '''
import threading


class Counter:
    def __init__(self):
        self._lock = threading.Lock()
        self._n = 0

    def increment(self):
        with self._lock:
            self._n += 1
            return self._n
''', note="thread-safe counter"),

    case("h_clean_py_safe_load", "python", "config.py", '''
import yaml


def parse(text):
    return yaml.safe_load(text)
''', note="decoy: safe_load"),

    case("h_clean_py_allowlist_redirect", "python", "login.py", '''
from urllib.parse import urlparse

from flask import Flask, redirect, request

app = Flask(__name__)
ALLOWED_HOSTS = {"example.com"}


@app.route("/after-login")
def after_login():
    target = request.args.get("next", "/")
    host = urlparse(target).netloc
    if host and host not in ALLOWED_HOSTS:
        target = "/"
    return redirect(target)
''', note="decoy: redirect target validated against an allow-list"),

    case("h_clean_py_pbkdf2", "python", "passwords.py", '''
import hashlib
import os


def hash_password(password: str):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt, digest
''', note="decoy: salted, slow password hash"),

    case("h_clean_py_stream_lines", "python", "lines.py", '''
def long_lines(path, limit):
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\\n") for line in f if len(line) > limit]
''', note="correct file handling"),

    case("h_clean_py_dict_copy", "python", "prune.py", '''
def drop_empty(data):
    for key in list(data):
        if not data[key]:
            del data[key]
    return data
''', note="decoy: iterates over a copy of the keys"),

    case("h_clean_py_closure_default", "python", "hooks.py", '''
def make_handlers():
    return [lambda i=i: i * 2 for i in range(3)]
''', note="decoy: default arg binds the loop variable"),

    case("h_clean_js_exec_file", "javascript", "ls.js", '''
const { execFile } = require("child_process");

app.get("/list", (req, res) => {
  execFile("ls", [req.query.dir], (err, stdout) => res.send(stdout));
});
''', note="decoy: no shell, arguments passed as an array"),

    case("h_clean_js_let_closure", "javascript", "timers.js", '''
function schedule() {
  for (let i = 0; i < 3; i++) {
    setTimeout(() => console.log(i), 100);
  }
}
''', note="decoy: let gives a fresh binding per iteration"),

    case("h_clean_go_make_map", "go", "counts.go", '''
package main

func tally(words []string) map[string]int {
	counts := make(map[string]int)
	for _, w := range words {
		counts[w]++
	}
	return counts
}
''', note="initialised map"),

    case("h_clean_java_equals", "java", "Auth.java", '''
public class Auth {
    public boolean isAdmin(String role) {
        return "admin".equals(role);
    }
}
''', note="decoy: null-safe equals"),

    case("h_clean_c_bounds", "c", "zero.c", '''
void clear(void) {
    char buf[10];
    for (int i = 0; i < 10; i++) {
        buf[i] = 0;
    }
}
''', note="correct loop bound"),
]

KW = {
    "h_py_sql_format": [r"sql|inject|format|string.?based|parameteri"],
    "h_py_os_system": [r"command|shell|os\.system|inject|S605|S607"],
    "h_py_assert_auth": [r"assert|authoriz|permission|-O|optimi|S101|privilege|admin"],
    "h_py_dict_mutation": [r"mutat|modif|iterat|runtimeerror|delet|size"],
    "h_py_late_binding": [r"closure|late|bind|lambda|loop variable|B023|last"],
    "h_py_jwt_noverify": [r"jwt|signature|verif|decode|token"],
    "h_js_proto_pollution": [r"prototype|pollut|__proto__|merge|inject"],
    "h_js_cmd_injection": [r"command|shell|exec|inject"],
    "h_js_var_closure": [r"var|closure|scope|let|loop|settimeout|3"],
    "h_go_nil_map": [r"nil|map|panic|initiali"],
    "h_java_string_eq": [r"equals|==|reference|string compar|compar"],
    "h_c_buffer_off_by_one": [r"off.?by.?one|bound|overflow|<=|out of|buffer|index"],
}
for _c in CASES:
    if _c["bugs"]:
        assert _c["id"] in KW and len(KW[_c["id"]]) == len(_c["bugs"]), _c["id"]
        for _b, _k in zip(_c["bugs"], KW[_c["id"]], strict=True):
            _b["kw"] = _k
