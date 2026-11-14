"""Build a made-up legacy repo with real git history for the gitscope tests.

History (all content is invented):

    master:  A(init) ── B(branch point) ── H(HOTFIX-9, not merged into develop)
                              \\
    develop:                   D1(DEMO-1) ── D2(DEMO-2) ── U(no ticket ID)

- D1 changes the shared OrderService.CalcTotal.
- D2 adds PointScreen with the new label 「ポイント利用」, calls CalcTotal from Invoice.cs (outside the
  scoped paths) and edits a doc with a Japanese file name.
- U touches util/Format.cs only, which mentions no scoped symbol.
- H adds hotfix/Patch.cs on master after the branch point.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

JP_DOC = "docs/注文仕様.txt"


@dataclass
class FixtureRepo:
    path: Path
    commits: dict[str, str] = field(default_factory=dict)

    def git(self, *args: str) -> str:
        return _git(self.path, *args)


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotepath=off", *args],
        capture_output=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    return proc.stdout


def _write(repo: Path, rel: str, text: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def _commit(repo: Path, message: str, stamp: int) -> str:
    env = dict(
        os.environ,
        GIT_AUTHOR_DATE=f"2026-01-01T00:{stamp:02d}:00+00:00",
        GIT_COMMITTER_DATE=f"2026-01-01T00:{stamp:02d}:00+00:00",
    )
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", message, env=env)
    return _git(repo, "rev-parse", "HEAD").strip()


SCREEN = """\
namespace Demo.Screens
{
    // 注文確定画面
    public class OrderConfirm
    {
        public string ButtonLabel = "「確定」";

        public decimal OnConfirm(Order order)
        {
            return new OrderService().CalcTotal(order);
        }
    }
}
"""

SERVICE_V1 = """\
namespace Demo.Services
{
    public class OrderService
    {
        public decimal CalcTotal(Order order)
        {
            return order.Subtotal + order.Tax;
        }
    }
}
"""

SERVICE_V2 = SERVICE_V1.replace(
    "return order.Subtotal + order.Tax;", "return order.Subtotal + order.Tax - order.Discount;"
)

INVOICE_V1 = """\
namespace Demo.Reports
{
    public class Invoice
    {
        public string Title = "請求書";
    }
}
"""

INVOICE_V2 = INVOICE_V1.replace(
    '        public string Title = "請求書";\n',
    '        public string Title = "請求書";\n        public decimal Total(Order o) => new OrderService().CalcTotal(o);\n',
)

POINT_SCREEN = """\
namespace Demo.Screens
{
    public class PointScreen
    {
        public string ButtonLabel = "「ポイント利用」";
    }
}
"""


def make_repo(root: Path) -> FixtureRepo:
    repo = root / "demo-legacy"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "Fixture Bot")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    fx = FixtureRepo(repo)

    _write(repo, "src/screens/OrderConfirm.cs", SCREEN)
    _write(repo, "src/services/OrderService.cs", SERVICE_V1)
    _write(repo, "src/reports/Invoice.cs", INVOICE_V1)
    _write(repo, "src/util/Format.cs", "public static class Format { public static string Yen(decimal v) => v.ToString(); }\n")
    _write(repo, "db/sp_order_total.sql", "CREATE PROCEDURE sp_order_total AS SELECT 1;\n")
    _write(repo, "config/app.config", "<configuration><add key=\"TaxRate\" value=\"0.1\"/></configuration>\n")
    _write(repo, "batch/nightly_close.bat", "echo nightly\n")
    _write(repo, JP_DOC, "注文確定の仕様メモ\n")
    fx.commits["A"] = _commit(repo, "chore: initial import", 1)

    _write(repo, "README.txt", "demo legacy app\n")
    fx.commits["B"] = _commit(repo, "docs: add readme", 2)

    _git(repo, "branch", "develop")

    _write(repo, "src/hotfix/Patch.cs", "public class Patch { }\n")
    fx.commits["H"] = _commit(repo, "HOTFIX-9: emergency patch on production", 3)

    _git(repo, "checkout", "-q", "develop")
    _write(repo, "src/services/OrderService.cs", SERVICE_V2)
    fx.commits["D1"] = _commit(repo, "DEMO-1: apply discount in total", 4)

    _write(repo, "src/screens/PointScreen.cs", POINT_SCREEN)
    _write(repo, "src/reports/Invoice.cs", INVOICE_V2)
    _write(repo, JP_DOC, "注文確定の仕様メモ\nポイント利用を追加\n")
    fx.commits["D2"] = _commit(repo, "feat: point usage screen\n\nRefs DEMO-2", 5)

    _write(repo, "src/util/Format.cs", "public static class Format { public static string Yen(decimal v) => v.ToString(\"N0\"); }\n")
    fx.commits["U"] = _commit(repo, "tidy formatting", 6)

    _git(repo, "checkout", "-q", "master")
    return fx
