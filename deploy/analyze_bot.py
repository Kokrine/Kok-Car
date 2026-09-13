"""Find the Playwright lifecycle bugs in a bot's source, by parsing it.

The "Target page, context or browser has been closed" failure always comes
from the same few shapes of code. This walks the bot's Python files with the
ast module - no guessing from filenames, no regex - and reports every place
that needs to change, with line numbers and a specific instruction.

    python deploy/analyze_bot.py [directory]

Exit code is 0 when nothing needs changing, 1 when findings were reported.
"""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "virtualenv",
    "site-packages", ".cache",
    # our own files: the manager, its tests, and the diagnostic tools all
    # launch browsers on purpose
    "vinpro", "deploy", "tests",
}

BROWSER_TYPES = {"chromium", "firefox", "webkit"}

# Telegram handler parameters, used to tell a request handler from setup code.
HANDLER_HINTS = {"update", "message", "callback_query", "context"}

# Calls that put text in front of a user.
USER_FACING = {
    "reply_text", "reply_html", "reply_markdown", "send_message",
    "edit_message_text", "edit_text", "answer", "answer_callback_query",
    "reply_document", "reply_photo",
}
# Variables that usually hold an exception.
EXC_NAMES = {"e", "ex", "exc", "err", "error", "exception"}

# Words that must never reach a user: the source site's name or address.
# Override with VINPRO_SCRUB_WORDS="word1,word2".
BLOCKED_WORDS = tuple(
    w.strip().lower()
    for w in ("cargopolo," + os.environ.get("VINPRO_SCRUB_WORDS", "")).split(",")
    if w.strip()
)


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    detail: str
    fix: str


@dataclass
class FileReport:
    path: str
    findings: list[Finding] = field(default_factory=list)
    uses_playwright: bool = False
    global_browser: list[int] = field(default_factory=list)


def _attr_chain(node: ast.AST) -> str:
    """Render a.b.c() targets as 'a.b.c' so they can be matched by name."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _blocked_in_call(call: ast.Call) -> str:
    """The blocked word a user-facing call would print, if any."""
    for node in ast.walk(call):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            for word in BLOCKED_WORDS:
                if word in lowered:
                    return word
    return ""


def _mentions_exception(call: ast.Call) -> bool:
    """True when a user-facing call interpolates an exception into its text."""
    return _mentions_exception_expr(call)


def _mentions_exception_expr(expr: ast.AST) -> bool:
    for node in ast.walk(expr):
        if isinstance(node, ast.Name) and node.id in EXC_NAMES:
            return True
        if isinstance(node, ast.Call):
            fn = _attr_chain(node.func)
            if fn in ("str", "repr") or fn.endswith(".format_exc"):
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id in EXC_NAMES:
                        return True
                if fn.endswith(".format_exc"):
                    return True
    return False


def _has_timeout(call: ast.Call) -> bool:
    return any(kw.arg == "timeout" for kw in call.keywords)


class BotVisitor(ast.NodeVisitor):
    def __init__(self, path: str, report: FileReport) -> None:
        self.path = path
        self.report = report
        self.func_stack: list[ast.AST] = []
        # Names bound to a launched browser, so b.close() is caught as well
        # as browser.close().
        self.browser_names: set[str] = {"browser"}
        # Variables holding text built from an exception. A handler often
        # builds the message first and sends it a line later.
        self.tainted: set[str] = set()

    # -- scope tracking -------------------------------------------------
    def visit_FunctionDef(self, node):  # noqa: N802
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        self._visit_func(node)

    def _visit_func(self, node):
        # Tainted names are per function: a variable named `msg` in one
        # handler says nothing about `msg` in the next.
        outer_tainted = self.tainted
        self.tainted = set()
        self.func_stack.append(node)
        self.generic_visit(node)
        self.func_stack.pop()
        self.tainted = outer_tainted

    def _current_func(self):
        return self.func_stack[-1] if self.func_stack else None

    def _in_handler(self) -> bool:
        """True when the enclosing function looks like a per-request handler."""
        func = self._current_func()
        if func is None:
            return False
        args = {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}
        return bool(args & HANDLER_HINTS)

    def _add(self, line, kind, detail, fix):
        self.report.findings.append(Finding(self.path, line, kind, detail, fix))

    # -- the interesting calls ------------------------------------------
    def visit_Call(self, node):  # noqa: N802
        target = _attr_chain(node.func)
        tail = target.rsplit(".", 1)[-1] if target else ""
        parent = target.rsplit(".", 2)[-2] if target.count(".") >= 1 else ""

        if tail in {"async_playwright", "sync_playwright"} or tail == "start":
            if tail in {"async_playwright", "sync_playwright"}:
                self.report.uses_playwright = True
            if tail == "sync_playwright":
                self._add(
                    node.lineno,
                    "SYNC-API",
                    "sync_playwright() inside an async bot blocks the event "
                    "loop and cannot be shared between requests",
                    "switch to async_playwright, or let vinpro handle it",
                )

        if tail == "launch" and parent in BROWSER_TYPES:
            self.report.uses_playwright = True
            where = "inside a request handler" if self._in_handler() else "at setup"
            self._add(
                node.lineno,
                "LAUNCH",
                f"browser launched {where}",
                "delete this; render_with_retry() owns the browser",
            )

        if tail == "close":
            obj = target.rsplit(".", 1)[0]
            known = obj in self.browser_names
            named = any(w in obj.lower() for w in ("browser", "chromium", "playwright"))
            if known or named:
                self._add(
                    node.lineno,
                    "CLOSE",
                    f"{target}() closes a browser other requests may be using",
                    "delete this; only manager.shutdown() closes the browser",
                )

        if tail in USER_FACING:
            word = _blocked_in_call(node)
            if word:
                self._add(
                    node.lineno,
                    "BRAND",
                    f"{tail}() shows the text \"{word}\" to the user",
                    "remove it - users must not learn where the data comes from",
                )

        sends_exception = _mentions_exception(node) or any(
            isinstance(a, ast.Name) and a.id in self.tainted
            for a in list(node.args) + [k.value for k in node.keywords]
        )
        if tail in USER_FACING and sends_exception:
            self._add(
                node.lineno,
                "LEAK",
                f"{tail}() sends the raw error text to the user - it can "
                "carry the source URL, ports and file paths",
                "send vinpro.user_errors.user_message(exc) instead",
            )

        if tail in {"wait_for", "wait_for_selector", "goto", "click", "inner_text"}:
            if not _has_timeout(node):
                self._add(
                    node.lineno,
                    "NO-TIMEOUT",
                    f"{tail}() has no explicit timeout",
                    "pass timeout=... so a slow page fails as a timeout",
                )

        self.generic_visit(node)

    # -- module-level browser -------------------------------------------
    @staticmethod
    def _is_launch_call(value: ast.AST) -> bool:
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call):
            return False
        target = _attr_chain(value.func)
        parts = target.rsplit(".", 2)
        return (
            parts[-1] == "launch"
            and len(parts) >= 2
            and parts[-2] in BROWSER_TYPES
        )

    def visit_AsyncWith(self, node):  # noqa: N802
        for item in node.items:
            if item.optional_vars is not None and self._is_launch_call(item.context_expr):
                if isinstance(item.optional_vars, ast.Name):
                    self.browser_names.add(item.optional_vars.id)
        self.generic_visit(node)

    def visit_Assign(self, node):  # noqa: N802
        if _mentions_exception_expr(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.tainted.add(t.id)
        if self._is_launch_call(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.browser_names.add(t.id)
        if not self.func_stack:
            for t in node.targets:
                if isinstance(t, ast.Name) and "browser" in t.id.lower():
                    self.report.global_browser.append(node.lineno)
        self.generic_visit(node)


def analyze_file(path: str) -> FileReport | None:
    report = FileReport(path=path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return None
    if "playwright" not in source and "Locator" not in source:
        return None
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        report.findings.append(
            Finding(path, exc.lineno or 0, "SYNTAX",
                    f"file does not parse: {exc.msg}",
                    "fix the syntax error before anything else")
        )
        return report
    BotVisitor(path, report).visit(tree)
    return report if (report.findings or report.uses_playwright) else None


def walk(root: str) -> list[FileReport]:
    reports = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".py"):
                rep = analyze_file(os.path.join(dirpath, name))
                if rep is not None:
                    reports.append(rep)
    return reports


ORDER = ["SYNTAX", "LAUNCH", "CLOSE", "LEAK", "BRAND", "SYNC-API", "NO-TIMEOUT"]


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    reports = walk(root)

    if not reports:
        print(f"No Playwright code found under {os.path.abspath(root)}.")
        print("Is this the bot's directory? Try:")
        print("  grep -rl --include='*.py' -e telegram -e playwright ~ | head")
        return 1

    print(f"\nScanning for {', '.join(BLOCKED_WORDS)} anywhere in the code...")
    mentions = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, 1):
                        low = line.lower()
                        if any(w in low for w in BLOCKED_WORDS):
                            mentions.append((path, n, line.strip()[:100]))
            except OSError:
                continue
    if mentions:
        print(f"  {len(mentions)} mention(s) - check each one is log-only, "
              "never sent to a user:")
        for path, n, text in mentions[:30]:
            print(f"    {path}:{n}  {text}")
    else:
        print("  none found")

    total = 0
    for rep in sorted(reports, key=lambda r: r.path):
        print(f"\n=== {rep.path}")
        if rep.global_browser:
            lines = ", ".join(str(n) for n in rep.global_browser)
            print(f"  line {lines}: module-level browser variable")
            print("      -> this is the shared browser that gets closed under")
            print("         other requests. Remove it; vinpro owns the browser.")
            total += 1
        for kind in ORDER:
            for f in [x for x in rep.findings if x.kind == kind]:
                print(f"  line {f.line:>4}  [{f.kind}] {f.detail}")
                print(f"              -> {f.fix}")
                total += 1
        if not rep.findings and not rep.global_browser:
            print("  uses Playwright, nothing to change")

    print("\n" + "=" * 64)
    kinds = {f.kind for rep in reports for f in rep.findings}
    if total:
        print(f"{total} place(s) to change.")
        if "LEAK" in kinds:
            print()
            print("Error text reaching users - replace with fixed messages:")
            print()
            print("    from vinpro.user_errors import log_message, user_message")
            print()
            print("    except Exception as exc:")
            print("        log.error(\"report failed: %s\", log_message(exc))")
            print("        await update.message.reply_text(user_message(exc))")
            print()
            print("Raw Playwright errors carry the source URL, ports, paths")
            print("and selectors. user_message() never derives from them.")
        if not (kinds & {"LAUNCH", "CLOSE", "SYNC-API"}):
            print("=" * 64)
            return 1
        print()
        print("Replace the launch/close code with:")
        print()
        print("    from vinpro.browser_manager import render_with_retry")
        print()
        print("    async def build_report(page, vin):")
        print("        ...   # the steps that are already in the handler")
        print()
        print("    pdf_bytes = await render_with_retry(build_report, vin)")
        print()
        print("Full example: vinpro/telegram_example.py")
    else:
        print("Nothing to change.")
    print("=" * 64)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
