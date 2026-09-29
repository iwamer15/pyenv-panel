"""ツールごとの requirements.txt を読み込むモジュール。

pip の requirements 形式のうち、「ライブラリ名 + バージョン指定」の行を対象にする。

対応:
  - `name==1.2.3` / `name>=1.0,<2` / `name~=1.4` / `name` （制約なし）
  - extras（`name[extra]`）、環境マーカー（`name; sys_platform == "win32"`）
  - コメント（行頭 `#` / 行末 ` #`）、行末 `\\` による行継続
  - `-r other.txt` / `--requirement other.txt` による別ファイルの取り込み（相対パスは読み込み元基準）

対応しない行（警告として返し、一覧には含めない）:
  - `-e` / URL・ローカルパス指定 / `--index-url` 等のpipオプション / `-c`（constraints）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

_INLINE_COMMENT_RE = re.compile(r"(^|\s)#.*$")
_INCLUDE_RE = re.compile(r"^(?:-r|--requirement)(?:\s+|=)(?P<path>.+)$")


class RequirementsFileError(Exception):
    pass


@dataclass
class ToolRequirement:
    name: str             # requirements.txt に書かれた表記（表示用）
    key: str              # 正規化名（PEP 503。pip list側との突き合わせに使う）
    specifier: str        # 例: "==1.26.4" / ">=1.24,<2" / ""（制約なし）
    extras: list[str] = field(default_factory=list)
    marker: str = ""      # 環境マーカー（例: 'sys_platform == "win32"'）
    source: str = ""      # 定義元ファイル名:行番号（ツールチップ表示用）

    def install_spec(self, specifier: str | None = None) -> str:
        """pip install に渡す文字列（マーカーは付けない。対象外の行は呼び出し側で除外済みの前提）。"""
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        spec = self.specifier if specifier is None else specifier
        return f"{self.name}{extras}{spec}"


@dataclass
class ParsedRequirements:
    requirements: list[ToolRequirement]
    warnings: list[str]


def _logical_lines(text: str):
    """行継続（末尾 \\）を連結し、(開始行番号, 行) を返す。"""
    buf = ""
    start = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not buf:
            start = lineno
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        yield start, buf + line
        buf = ""
    if buf:
        yield start, buf


def parse_requirements_text(text: str, source_name: str = "requirements.txt",
                            base_dir: Path | None = None, _seen: set[Path] | None = None) -> ParsedRequirements:
    reqs: list[ToolRequirement] = []
    warnings: list[str] = []
    seen = _seen if _seen is not None else set()

    for lineno, line in _logical_lines(text):
        line = _INLINE_COMMENT_RE.sub("", line).strip()
        if not line:
            continue
        where = f"{source_name}:{lineno}"

        include = _INCLUDE_RE.match(line)
        if include:
            if base_dir is None:
                warnings.append(f"{where}: -r の取り込み元ディレクトリが不明なためスキップしました: {line}")
                continue
            child = (base_dir / include.group("path").strip()).resolve()
            sub = parse_requirements_file(child, _seen=seen)
            reqs.extend(sub.requirements)
            warnings.extend(sub.warnings)
            continue

        if line.startswith("-"):
            warnings.append(f"{where}: pipオプション行は対象外です: {line}")
            continue

        try:
            req = Requirement(line)
        except InvalidRequirement as e:
            warnings.append(f"{where}: 解釈できない行をスキップしました（{e}）: {line}")
            continue
        if req.url:
            warnings.append(f"{where}: URL指定のライブラリは対象外です: {line}")
            continue

        reqs.append(ToolRequirement(
            name=req.name,
            key=canonicalize_name(req.name),
            specifier=str(req.specifier),
            extras=sorted(req.extras),
            marker=str(req.marker) if req.marker else "",
            source=where,
        ))

    return ParsedRequirements(reqs, warnings)


def parse_requirements_file(path: Path, _seen: set[Path] | None = None) -> ParsedRequirements:
    seen = _seen if _seen is not None else set()
    path = Path(path)
    resolved = path.resolve()
    if resolved in seen:
        return ParsedRequirements([], [f"{path.name}: -r の循環参照を検出したためスキップしました"])
    seen.add(resolved)

    if not path.exists():
        raise RequirementsFileError(f"requirements.txt が見つかりません: {path}")
    try:
        # Windowsのメモ帳で保存されたBOM付きUTF-8にも対応する
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise RequirementsFileError(f"requirements.txt を読み込めません: {path}（{e}）") from e

    return parse_requirements_text(text, source_name=path.name, base_dir=path.parent, _seen=seen)
