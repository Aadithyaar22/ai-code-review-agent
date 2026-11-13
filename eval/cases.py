"""Labeled benchmark for the code reviewer.

Each case is a small, self-contained snippet. `bugs` lists the ground-truth defects: `at` is a
substring that locates the defective line (first match), optional `end` extends the span to a
later line. `cat` is the expected category. A case with `bugs == []` is CLEAN code (many are
"decoys" that look risky but are safe) and any finding on it is a false positive.

Labels were written by the project author, snippets are intentionally minimal and otherwise
correct, so unlabeled-but-real issues should be rare; the harness lists every false positive so
they can be adjudicated by hand (see eval/adjudications.json).
"""


def B(at, cat, what, end=None):
    return {"at": at, "end": end, "cat": cat, "what": what}


def case(id, lang, file, code, bugs=(), note=""):
    return {"id": id, "lang": lang, "file": file, "code": code.lstrip("\n"), "bugs": list(bugs), "note": note}


CASES = [
    # ───────────────────────────── vulnerable / buggy ─────────────────────────────
    case("py_sqli_concat", "python", "users.py", '''
import sqlite3


def find_user(conn, name):
    cur = conn.cursor()
    cur.execute("SELECT id, email FROM users WHERE name = '" + name + "'")
    return cur.fetchall()
''', [B("cur.execute", "security", "SQL injection via string concatenation")]),

    case("py_sqli_fstring", "python", "admin.py", '''
def delete_user(cursor, user_id):
    cursor.execute(f"DELETE FROM users WHERE id = {user_id}")
    return cursor.rowcount
''', [B("cursor.execute", "security", "SQL injection via f-string")]),

    case("py_cmd_injection", "python", "net.py", '''
import subprocess


def ping(host):
    return subprocess.check_output("ping -c 1 " + host, shell=True)
''', [B("subprocess.check_output", "security", "OS command injection (shell=True + concatenation)")]),

    case("py_path_traversal", "python", "files.py", '''
import os

from flask import Flask, request, send_file

app = Flask(__name__)
BASE = "/srv/files"


@app.route("/download")
def download():
    name = request.args["name"]
    return send_file(os.path.join(BASE, name))
''', [B("send_file(", "security", "path traversal via user-controlled filename")]),

    case("py_pickle", "python", "api.py", '''
import pickle

from flask import Flask, request

app = Flask(__name__)


@app.route("/load", methods=["POST"])
def load():
    obj = pickle.loads(request.data)
    return str(obj)
''', [B("pickle.loads", "security", "unsafe deserialization of untrusted data")]),

    case("py_yaml_load", "python", "config.py", '''
import yaml


def parse(text):
    return yaml.load(text)
''', [B("yaml.load", "security", "yaml.load without safe loader")]),

    case("py_eval_calc", "python", "calc.py", '''
def calculate(expression):
    return eval(expression)
''', [B("eval(", "security", "eval of user-supplied expression")]),

    case("py_hardcoded_secret_md5", "python", "auth.py", '''
import hashlib

SECRET_KEY = "super-secret-signing-key-123"


def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()
''', [B("SECRET_KEY =", "security", "hardcoded secret"),
      B("hashlib.md5", "security", "weak hash for passwords")]),

    case("py_insecure_token", "python", "tokens.py", '''
import random
import string


def reset_token():
    return "".join(random.choice(string.ascii_letters) for _ in range(16))
''', [B("random.choice", "security", "non-cryptographic RNG for a security token")]),

    case("py_open_redirect", "python", "login.py", '''
from flask import Flask, redirect, request

app = Flask(__name__)


@app.route("/after-login")
def after_login():
    return redirect(request.args["next"])
''', [B("redirect(", "security", "open redirect")]),

    case("py_mutable_default", "python", "cart.py", '''
def add_item(item, items=[]):
    items.append(item)
    return items
''', [B("def add_item", "bug", "mutable default argument shared across calls")]),

    case("py_off_by_one", "python", "sums.py", '''
def total(items):
    result = 0
    for i in range(len(items) + 1):
        result += items[i]
    return result
''', [B("for i in range", "bug", "loop runs one past the end -> IndexError")]),

    case("py_div_zero", "python", "stats.py", '''
def average(values):
    return sum(values) / len(values)
''', [B("return sum", "bug", "ZeroDivisionError on empty list")]),

    case("py_resource_leak", "python", "cfg.py", '''
def read_config(path):
    f = open(path)
    data = f.read()
    return data.strip()
''', [B("f = open", "bug", "file handle never closed")]),

    case("py_none_deref", "python", "mail.py", '''
import re


def domain(email):
    m = re.match(r".+@(.+)", email)
    return m.group(1).lower()
''', [B("m.group", "bug", "re.match may return None -> AttributeError")]),

    case("py_toctou", "python", "store.py", '''
import os


def write_once(path, data):
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(data)
''', [B("if not os.path.exists", "bug", "check-then-act race (TOCTOU)")]),

    case("py_n_plus_one", "python", "orders.py", '''
def order_totals(db, order_ids):
    totals = {}
    for oid in order_ids:
        rows = db.execute("SELECT price, qty FROM items WHERE order_id = ?", (oid,)).fetchall()
        totals[oid] = sum(p * q for p, q in rows)
    return totals
''', [B("rows = db.execute", "performance", "N+1 queries inside a loop")]),

    case("py_quadratic_dedupe", "python", "dedupe.py", '''
def unique(items):
    seen = []
    for x in items:
        if x not in seen:
            seen.append(x)
    return seen
''', [B("if x not in seen", "performance", "O(n^2) membership test on a list")]),

    case("py_bare_except", "python", "loader.py", '''
import json


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}
''', [B("except:", "bug", "bare except silently swallows every error")]),

    case("py_infinite_loop", "python", "count.py", '''
def countdown(n):
    while n != 0:
        print(n)
        n -= 2
''', [B("while n != 0", "bug", "never terminates for odd n")]),

    case("py_is_string_compare", "python", "status.py", '''
def is_ok(status):
    if status is "ok":
        return True
    return False
''', [B('status is "ok"', "bug", "identity comparison with a string literal")]),

    case("js_xss_innerhtml", "javascript", "view.js", '''
function renderComment(comment) {
  document.getElementById("comments").innerHTML = comment.body;
}
''', [B("innerHTML", "security", "XSS via innerHTML with user content")]),

    case("js_eval", "javascript", "calc.js", '''
function calc(expr) {
  return eval(expr);
}
''', [B("eval(", "security", "eval of user input")]),

    case("js_hardcoded_key", "javascript", "pay.js", '''
const PAYMENT_API_SECRET = "live_9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c";

function charge(amount) {
  return gateway.charges.create({ amount, currency: "usd" }, { apiKey: PAYMENT_API_SECRET });
}
''', [B("PAYMENT_API_SECRET =", "security", "hardcoded live API key")]),

    case("js_missing_await", "javascript", "users.js", '''
async function getUser(id) {
  const res = fetch(`/api/users/${id}`);
  const data = await res.json();
  return data;
}
''', [B("const res = fetch", "bug", "missing await: res is a Promise")]),

    case("js_assign_in_condition", "javascript", "perm.js", '''
function canEdit(user) {
  if (user.role = "admin") {
    return true;
  }
  return false;
}
''', [B("user.role =", "bug", "assignment instead of comparison in condition")]),

    case("js_sql_injection", "javascript", "server.js", '''
app.get("/user/:id", async (req, res) => {
  const rows = await db.query("SELECT * FROM users WHERE id = " + req.params.id);
  res.json(rows);
});
''', [B("db.query", "security", "SQL injection from route parameter")]),

    case("js_off_by_one", "javascript", "sum.js", '''
function sum(arr) {
  let total = 0;
  for (let i = 0; i <= arr.length; i++) {
    total += arr[i];
  }
  return total;
}
''', [B("for (let i", "bug", "<= runs one past the end -> NaN")]),

    case("go_ignored_error", "go", "read.go", '''
package main

import (
	"fmt"
	"os"
)

func main() {
	data, _ := os.ReadFile("config.json")
	fmt.Println(len(data))
}
''', [B("os.ReadFile", "bug", "error from ReadFile ignored")]),

    case("go_sql_injection", "go", "db.go", '''
package main

import (
	"database/sql"
	"fmt"
)

func findUser(db *sql.DB, name string) (*sql.Rows, error) {
	query := fmt.Sprintf("SELECT id FROM users WHERE name = '%s'", name)
	return db.Query(query)
}
''', [B("fmt.Sprintf", "security", "SQL injection via Sprintf", end="db.Query")]),

    case("go_data_race", "go", "counter.go", '''
package main

import "sync"

var counter int

func increment(wg *sync.WaitGroup) {
	defer wg.Done()
	counter++
}

func main() {
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go increment(&wg)
	}
	wg.Wait()
}
''', [B("counter++", "bug", "unsynchronised write from many goroutines (data race)")]),

    case("java_sqli", "java", "UserDao.java", '''
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

public class UserDao {
    public ResultSet find(Connection conn, String name) throws SQLException {
        Statement st = conn.createStatement();
        return st.executeQuery("SELECT * FROM users WHERE name = '" + name + "'");
    }
}
''', [B("st.executeQuery", "security", "SQL injection with Statement + concatenation")]),

    case("java_npe", "java", "Lookup.java", '''
import java.util.Map;

public class Lookup {
    public int nameLength(Map<String, String> names, String key) {
        String name = names.get(key);
        return name.length();
    }
}
''', [B("name.length", "bug", "Map.get may return null -> NullPointerException")]),

    case("c_strcpy_overflow", "c", "copy.c", '''
#include <string.h>

void greet(const char *input) {
    char buf[16];
    strcpy(buf, input);
}
''', [B("strcpy", "security", "unbounded strcpy into a 16-byte buffer")]),

    case("c_format_string", "c", "log.c", '''
#include <stdio.h>

void log_message(const char *user_input) {
    printf(user_input);
}
''', [B("printf(user_input)", "security", "format string vulnerability")]),

    case("c_use_after_free", "c", "mem.c", '''
#include <stdlib.h>

void run(void) {
    char *p = malloc(10);
    free(p);
    p[0] = 'x';
}
''', [B("p[0]", "bug", "write after free")]),

    case("sh_unquoted_rm", "bash", "clean.sh", '''
#!/bin/bash
DIR=$1
rm -rf $DIR/*
''', [B("rm -rf", "bug", "unquoted/unchecked variable in rm -rf (empty DIR deletes /*)")]),

    # ───────────────────────────── clean code (incl. decoys) ─────────────────────────────
    case("clean_py_param_query", "python", "users.py", '''
import sqlite3


def find_user(conn: sqlite3.Connection, name: str):
    cur = conn.cursor()
    cur.execute("SELECT id, email FROM users WHERE name = ?", (name,))
    return cur.fetchall()
''', note="decoy: SQL looks risky but is parameterised"),

    case("clean_py_subprocess_list", "python", "net.py", '''
import subprocess


def ping(host: str) -> bytes:
    return subprocess.check_output(["ping", "-c", "1", host], timeout=5)
''', note="decoy: subprocess without a shell"),

    case("clean_py_with_open", "python", "cfg.py", '''
import json


def read_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
''', note="narrow except, context manager"),

    case("clean_py_env_secret", "python", "auth.py", '''
import hmac
import os


def verify(token: str) -> bool:
    secret = os.environ["API_SECRET"]
    return hmac.compare_digest(token, secret)
''', note="decoy: secret handling done right"),

    case("clean_py_average_guard", "python", "stats.py", '''
def average(values):
    if not values:
        return 0.0
    return sum(values) / len(values)
''', note="guarded division"),

    case("clean_py_safe_path", "python", "files.py", '''
import os

from flask import Flask, abort, request, send_file

app = Flask(__name__)
BASE = os.path.realpath("/srv/files")


@app.route("/download")
def download():
    path = os.path.realpath(os.path.join(BASE, request.args["name"]))
    if not path.startswith(BASE + os.sep):
        abort(400)
    return send_file(path)
''', note="decoy: user path is validated"),

    case("clean_py_secrets_token", "python", "tokens.py", '''
import secrets


def reset_token() -> str:
    return secrets.token_urlsafe(32)
''', note="CSPRNG"),

    case("clean_py_literal_eval", "python", "parse.py", '''
import ast


def parse_literal(text):
    return ast.literal_eval(text)
''', note="decoy: not eval()"),

    case("clean_py_set_dedupe", "python", "dedupe.py", '''
def unique(items):
    seen = set()
    result = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result
''', note="O(n) dedupe"),

    case("clean_py_none_default", "python", "cart.py", '''
def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
''', note="correct default-argument idiom"),

    case("clean_py_dataclass", "python", "model.py", '''
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def distance_to(self, other: "Point") -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5
''', note="plain correct code"),

    case("clean_py_retry", "python", "retry.py", '''
import time


def retry(fn, attempts=3, delay=0.5):
    for attempt in range(attempts):
        try:
            return fn()
        except ConnectionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * 2 ** attempt)
''', note="correct bounded retry"),

    case("clean_js_fetch_await", "javascript", "users.js", '''
async function getUser(id) {
  try {
    const res = await fetch(`/api/users/${encodeURIComponent(id)}`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error(err);
    return null;
  }
}
''', note="proper async/await + error handling"),

    case("clean_js_textcontent", "javascript", "view.js", '''
function renderComment(comment) {
  document.getElementById("comments").textContent = comment.body;
}
''', note="decoy: textContent is safe"),

    case("clean_js_param_query", "javascript", "server.js", '''
app.get("/user/:id", async (req, res) => {
  const { rows } = await db.query("SELECT * FROM users WHERE id = $1", [req.params.id]);
  res.json(rows);
});
''', note="decoy: parameterised query"),

    case("clean_js_sum", "javascript", "sum.js", '''
function sum(arr) {
  let total = 0;
  for (let i = 0; i < arr.length; i++) {
    total += arr[i];
  }
  return total;
}
''', note="correct loop bound"),

    case("clean_go_error_handled", "go", "read.go", '''
package main

import (
	"fmt"
	"os"
)

func main() {
	data, err := os.ReadFile("config.json")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Println(len(data))
}
''', note="error handled"),

    case("clean_go_mutex", "go", "counter.go", '''
package main

import "sync"

type Counter struct {
	mu sync.Mutex
	n  int
}

func (c *Counter) Inc() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.n++
}
''', note="decoy: increment under a mutex"),

    case("clean_java_prepared", "java", "UserDao.java", '''
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

public class UserDao {
    public ResultSet find(Connection conn, String name) throws SQLException {
        PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE name = ?");
        ps.setString(1, name);
        return ps.executeQuery();
    }
}
''', note="decoy: PreparedStatement"),

    case("clean_c_snprintf", "c", "copy.c", '''
#include <stdio.h>

void greet(const char *input) {
    char buf[16];
    snprintf(buf, sizeof buf, "%s", input);
}
''', note="decoy: bounded copy"),

    case("clean_sh_quoted_rm", "bash", "clean.sh", '''
#!/bin/bash
set -euo pipefail
DIR="${1:?usage: clean.sh DIR}"
rm -rf "${DIR:?}"/*
''', note="decoy: guarded + quoted rm -rf"),
]


# Semantic keywords: a finding only counts as finding a bug if it touches the bug's line AND its text
# (title + description + rule id) matches one of these patterns. This stops "right line, wrong problem"
# findings from being scored as hits. Patterns are deliberately generous about wording.
KW = {
    "py_sqli_concat": [r"sql|inject|concatenat|string.?based|parameteri"],
    "py_sqli_fstring": [r"sql|inject|f-?string|string.?based|parameteri"],
    "py_cmd_injection": [r"command|shell|subprocess|inject|S602"],
    "py_path_traversal": [r"travers|path|director|arbitrary file|sanitiz|\.\./"],
    "py_pickle": [r"pickle|deserial|untrusted"],
    "py_yaml_load": [r"yaml|deserial|unsafe|safe_load|arbitrary"],
    "py_eval_calc": [r"eval|code (exec|inject)|arbitrary code|insecure function"],
    "py_hardcoded_secret_md5": [r"secret|hardcod|credential|password", r"md5|hash|weak|insecure|crypto"],
    "py_insecure_token": [r"random|secrets|crypto|predict|pseudo|S311"],
    "py_open_redirect": [r"redirect|validat|untrusted|\bnext\b|unvalidated"],
    "py_mutable_default": [r"mutable|default|B006"],
    "py_off_by_one": [r"off.?by.?one|index|out of (range|bounds)|range|bound"],
    "py_div_zero": [r"zero|division|empty"],
    "py_resource_leak": [r"leak|clos|context manager|with open|resource|file handle"],
    "py_none_deref": [r"none|null|attributeerror|no match|invalid email|match"],
    "py_toctou": [r"race|toctou|check.?then|time.?of.?check|atomic|exists"],
    "py_n_plus_one": [r"n\s?\+\s?1|repeated|per.?(order|id|iteration)|each (order|id|iteration)|in a loop|inside (a |the )?loop|batch|single quer|multiple quer|many quer|round.?trip"],
    "py_quadratic_dedupe": [r"o\(n|quadratic|inefficien|membership|linear (search|scan)|performance|use a set"],
    "py_bare_except": [r"bare|except:|swallow|all exceptions|catch.?all|broad|silent|too (broad|general)|specific exception"],
    "py_infinite_loop": [r"infinite|never terminat|endless|terminat|odd"],
    "py_is_string_compare": [r"F632|==|identity|literal|compar|\bis\b"],
    "js_xss_innerhtml": [r"xss|cross.?site|innerhtml|inject|sanitiz|escape"],
    "js_eval": [r"eval|code (exec|inject)|arbitrary|inject"],
    "js_hardcoded_key": [r"secret|hardcod|key|credential"],
    "js_missing_await": [r"await|promise|async|not awaited|asynchron"],
    "js_assign_in_condition": [r"assign|comparison|==|condition"],
    "js_sql_injection": [r"sql|inject|parameter|concat"],
    "js_off_by_one": [r"off.?by.?one|<=|bound|undefined|nan|out of|index|length"],
    "go_ignored_error": [r"error|ignor|unhandled|\berr\b"],
    "go_sql_injection": [r"sql|inject|sprintf|parameter"],
    "go_data_race": [r"race|sync|mutex|atomic|concurren|goroutine"],
    "java_sqli": [r"sql|inject|prepared|concat|parameter"],
    "java_npe": [r"null|npe|nullpointer|\.get\("],
    "c_strcpy_overflow": [r"overflow|strcpy|bound|buffer"],
    "c_format_string": [r"format|printf"],
    "c_use_after_free": [r"free|use.?after|dangling|freed"],
    "sh_unquoted_rm": [r"quot|delet|\brm\b|empty|unset|glob|word.?split|variable|data loss"],
}
for _c in CASES:
    if _c["bugs"]:
        assert _c["id"] in KW and len(KW[_c["id"]]) == len(_c["bugs"]), _c["id"]
        for _b, _k in zip(_c["bugs"], KW[_c["id"]], strict=True):
            _b["kw"] = _k
