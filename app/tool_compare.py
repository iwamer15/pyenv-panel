"""登録ツールの requirements.txt と対象Pythonの実環境を突き合わせる。

- 全ツールの requirements.txt に出てくるライブラリを1つの一覧（LibraryTable）にまとめる
- 行ごとに「どのツールが、どのバージョン指定で必要としているか」を保持し、
  表示中のツール（または全ツール合算）の要件に対して、インストール済バージョンが
  古い／新しい／一致／条件内／未インストール かを判定する
- 複数ツールで同じライブラリのバージョン指定が両立しない場合は「競合」として検出する
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from packaging.markers import InvalidMarker, Marker, UndefinedComparison, UndefinedEnvironmentName
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .requirements_file import ToolRequirement


class LibStatus(str, Enum):
    MATCH = "一致"
    SATISFIED = "条件内"
    OLDER = "古い"
    NEWER = "新しい"
    MISSING = "未インストール"
    UNCONSTRAINED = "制約なし"
    UNKNOWN = "要確認"
    CONFLICT = "競合"           # ツール同士の要件が両立しない（全ツール合算表示のみ）
    NOT_APPLICABLE = "対象外"   # 環境マーカーによりこのPCでは不要
    NOT_REQUIRED = "-"          # 表示中のツールでは使わない


# 要件を満たしておらず、インストール/更新で解消すべき状態
ACTION_STATUSES = {LibStatus.MISSING, LibStatus.OLDER, LibStatus.NEWER, LibStatus.UNKNOWN}


def compare_version(installed: str | None, specifier: str) -> LibStatus:
    """インストール済バージョンを要件（SpecifierSet文字列）と比較する。"""
    if installed is None:
        return LibStatus.MISSING
    if not specifier:
        return LibStatus.UNCONSTRAINED
    try:
        v = Version(installed)
        spec_set = SpecifierSet(specifier)
    except (InvalidVersion, InvalidSpecifier):
        return LibStatus.UNKNOWN

    if spec_set.contains(v, prereleases=True):
        return LibStatus.MATCH if any(s.operator in ("==", "===") for s in spec_set) else LibStatus.SATISFIED

    directions: set[LibStatus] = set()
    for s in spec_set:
        if s.contains(v, prereleases=True):
            continue
        op = s.operator
        if op in (">=", ">"):
            directions.add(LibStatus.OLDER)
        elif op in ("<", "<="):
            directions.add(LibStatus.NEWER)
        elif op in ("==", "~="):
            # "==1.26.*" のワイルドカードは前方一致の基準バージョンと比べる
            try:
                base = Version(s.version[:-2] if s.version.endswith(".*") else s.version)
            except InvalidVersion:
                directions.add(LibStatus.UNKNOWN)
                continue
            directions.add(LibStatus.OLDER if v < base else LibStatus.NEWER)
        else:  # "!=" / "===" は古い・新しいを判断できない
            directions.add(LibStatus.UNKNOWN)
    return directions.pop() if len(directions) == 1 else LibStatus.UNKNOWN


def marker_applies(marker: str, env: dict[str, str] | None) -> bool:
    """環境マーカーが対象Pythonで有効か。評価できない場合は「必要」側に倒す。"""
    if not marker:
        return True
    try:
        return Marker(marker).evaluate(env) if env else Marker(marker).evaluate()
    except (InvalidMarker, UndefinedComparison, UndefinedEnvironmentName):
        return True


def _bump(release: tuple[int, ...]) -> Version:
    """(1, 26) → 1.27。"==1.26.*" / "~=1.4.2" の上限（未満）を求めるのに使う。"""
    return Version(".".join(str(x) for x in release[:-1] + (release[-1] + 1,)))


def _interval(spec: str):
    """SpecifierSet を「下限〜上限」の区間に近似する。(lo, lo_incl, hi, hi_incl)。None は無制限。

    "!=" / "===" は区間では表せないため無視する（競合検出の見逃しはあっても誤検出はしない側に倒す）。
    """
    lo = hi = None
    lo_incl = hi_incl = True

    def raise_lo(v: Version, incl: bool):
        nonlocal lo, lo_incl
        if lo is None or v > lo or (v == lo and not incl):
            lo, lo_incl = v, incl

    def lower_hi(v: Version, incl: bool):
        nonlocal hi, hi_incl
        if hi is None or v < hi or (v == hi and not incl):
            hi, hi_incl = v, incl

    for s in SpecifierSet(spec):
        op, ver = s.operator, s.version
        try:
            if op == "==" and ver.endswith(".*"):
                base = Version(ver[:-2])
                raise_lo(base, True)
                lower_hi(_bump(base.release), False)
            elif op == "==":
                v = Version(ver)
                raise_lo(v, True)
                lower_hi(v, True)
            elif op == "~=":
                v = Version(ver)
                raise_lo(v, True)
                lower_hi(_bump(v.release[:-1]), False)
            elif op in (">=", ">"):
                raise_lo(Version(ver), op == ">=")
            elif op in ("<", "<="):
                lower_hi(Version(ver), op == "<=")
        except InvalidVersion:
            continue
    return lo, lo_incl, hi, hi_incl


def specs_compatible(spec_a: str, spec_b: str) -> bool:
    """2つのバージョン指定を同時に満たすバージョンが（区間として）存在しうるか。"""
    try:
        a_lo, a_lo_i, a_hi, a_hi_i = _interval(spec_a)
        b_lo, b_lo_i, b_hi, b_hi_i = _interval(spec_b)
    except InvalidSpecifier:
        return True
    # 下限は大きい方、上限は小さい方を取って区間が空かどうかを見る
    lo, lo_i = (a_lo, a_lo_i) if b_lo is None or (a_lo is not None and (a_lo, not a_lo_i) > (b_lo, not b_lo_i)) else (b_lo, b_lo_i)
    hi, hi_i = (a_hi, a_hi_i) if b_hi is None or (a_hi is not None and (a_hi, a_hi_i) < (b_hi, b_hi_i)) else (b_hi, b_hi_i)
    if lo is None or hi is None:
        return True
    return lo < hi or (lo == hi and lo_i and hi_i)


def detect_conflicts(reqs_by_tool: dict[str, ToolRequirement], tool_names: dict[str, str]) -> list[str]:
    """ツール同士で、同じライブラリのバージョン指定が両立しない組み合わせを列挙する。"""
    messages: list[str] = []
    items = [(tid, r) for tid, r in reqs_by_tool.items() if r.specifier]
    for i, (tid_a, req_a) in enumerate(items):
        for tid_b, req_b in items[i + 1:]:
            if not specs_compatible(req_a.specifier, req_b.specifier):
                messages.append(
                    f"{tool_names.get(tid_a, tid_a)} は {req_a.specifier}、"
                    f"{tool_names.get(tid_b, tid_b)} は {req_b.specifier} を要求（両立不可）"
                )
    return messages


@dataclass
class RowEval:
    needed: bool
    specifier: str
    status: LibStatus
    install_spec: str | None   # pip install に渡す文字列（needed でない場合は None）


@dataclass
class LibraryRow:
    key: str
    name: str
    installed_version: str | None
    reqs: dict[str, ToolRequirement] = field(default_factory=dict)       # このPCで必要な要件（tool_id → 要件）
    excluded: dict[str, ToolRequirement] = field(default_factory=dict)   # 環境マーカーで対象外になった要件
    conflicts: list[str] = field(default_factory=list)

    def evaluate(self, tool_id: str | None) -> RowEval:
        """tool_id=None は全ツール合算（すべてのバージョン指定を同時に満たす必要がある）。"""
        if tool_id is None:
            reqs = list(self.reqs.values())
            if not reqs:
                return RowEval(False, "", LibStatus.NOT_APPLICABLE, None)
            parts = [r.specifier for r in reqs if r.specifier]
            spec = str(SpecifierSet(",".join(parts))) if parts else ""
            if self.conflicts:
                # 全ツールを同時に満たすバージョンが無いため、合算ではインストール対象にしない
                return RowEval(True, spec, LibStatus.CONFLICT, None)
            extras = sorted({e for r in reqs for e in r.extras})
            base = ToolRequirement(self.name, self.key, spec, extras)
            return RowEval(True, spec, compare_version(self.installed_version, spec), base.install_spec())

        req = self.reqs.get(tool_id)
        if req is None:
            if tool_id in self.excluded:
                return RowEval(False, self.excluded[tool_id].specifier, LibStatus.NOT_APPLICABLE, None)
            return RowEval(False, "", LibStatus.NOT_REQUIRED, None)
        return RowEval(True, req.specifier, compare_version(self.installed_version, req.specifier), req.install_spec())


@dataclass
class LibraryTable:
    rows: list[LibraryRow]
    tool_names: dict[str, str]                       # tool_id → 表示名（登録順）
    tool_warnings: dict[str, list[str]]              # 解釈できなかった行など
    tool_errors: dict[str, str]                      # requirements.txt 自体を読めなかったツール

    def summary(self, tool_id: str | None) -> dict[LibStatus, int]:
        counts: dict[LibStatus, int] = {}
        for row in self.rows:
            ev = row.evaluate(tool_id)
            if ev.needed:
                counts[ev.status] = counts.get(ev.status, 0) + 1
        return counts

    def action_specs(self, tool_id: str | None) -> list[tuple[LibraryRow, RowEval]]:
        """インストール/更新で解消すべき行（未インストール・古い・新しい・要確認）。"""
        out = []
        for row in self.rows:
            ev = row.evaluate(tool_id)
            if ev.needed and ev.status in ACTION_STATUSES:
                out.append((row, ev))
        return out


def build_library_table(
    tool_reqs: dict[str, list[ToolRequirement]],
    tool_names: dict[str, str],
    installed: dict[str, str],
    marker_env: dict[str, str] | None = None,
    tool_warnings: dict[str, list[str]] | None = None,
    tool_errors: dict[str, str] | None = None,
) -> LibraryTable:
    """installed は {パッケージ名: バージョン}（名前の表記揺れはここで正規化する）。"""
    installed_norm = {canonicalize_name(k): v for k, v in installed.items()}
    rows: dict[str, LibraryRow] = {}

    for tool_id, reqs in tool_reqs.items():
        for req in reqs:
            row = rows.get(req.key)
            if row is None:
                row = rows[req.key] = LibraryRow(req.key, req.name, installed_norm.get(req.key))
            target = row.reqs if marker_applies(req.marker, marker_env) else row.excluded
            if tool_id in target:
                # 同じファイル内で同じライブラリが複数行ある場合は条件を AND で結合する
                prev = target[tool_id]
                merged = ",".join(p for p in (prev.specifier, req.specifier) if p)
                prev.specifier = str(SpecifierSet(merged)) if merged else ""
                prev.extras = sorted(set(prev.extras) | set(req.extras))
            else:
                target[tool_id] = ToolRequirement(req.name, req.key, req.specifier, list(req.extras), req.marker, req.source)

    for row in rows.values():
        row.conflicts = detect_conflicts(row.reqs, tool_names)

    return LibraryTable(
        rows=sorted(rows.values(), key=lambda r: r.key),
        tool_names=tool_names,
        tool_warnings=tool_warnings or {},
        tool_errors=tool_errors or {},
    )
