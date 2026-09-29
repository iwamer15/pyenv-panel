"""ツール登録簿（runtime/config/tools.json）の読み書き。

「どのツールがどの requirements.txt を必要とするか」を管理する。
requirements.txt の場所は次のどちらでもよい:
  - 共有ランタイム内に保存したもの（相対パス。例: config/tools/<id>/requirements.txt）
    → 全端末で同じ内容を参照できる。登録時に「共有ランタイムへ保存」を選ぶとここへコピーされる
  - 各ツールのリポジトリ等にある既存ファイル（絶対パス）

tools.json の例:
    {
      "schema_version": 1,
      "allow_online": true,
      "tools": [
        {"id": "report-tool", "name": "帳票出力ツール",
         "requirements": "config/tools/report-tool/requirements.txt",
         "description": "月次帳票の自動作成"}
      ]
    }
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import RuntimePaths

SCHEMA_VERSION = 1
_ID_SAFE_RE = re.compile(r"[^0-9A-Za-z_.-]+")


class ToolsRegistryError(Exception):
    pass


@dataclass
class ToolEntry:
    id: str
    name: str
    requirements: str   # 共有ランタイムルートからの相対パス、または絶対パス
    description: str = ""


@dataclass
class ToolsRegistry:
    tools: list[ToolEntry]
    allow_online: bool = True   # PyPI（インターネット）からの取得を既定で許可するか

    def find(self, tool_id: str) -> ToolEntry | None:
        return next((t for t in self.tools if t.id == tool_id), None)


def tools_json_path(paths: RuntimePaths) -> Path:
    return paths.root / "config" / "tools.json"


def resolve_requirements_path(paths: RuntimePaths, tool: ToolEntry) -> Path:
    p = Path(tool.requirements)
    return p if p.is_absolute() else paths.root / p


def load_registry(paths: RuntimePaths) -> ToolsRegistry:
    path = tools_json_path(paths)
    if not path.exists():
        return ToolsRegistry(tools=[])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        tools = [
            ToolEntry(
                id=str(t["id"]),
                name=str(t.get("name") or t["id"]),
                requirements=str(t["requirements"]),
                description=str(t.get("description", "")),
            )
            for t in raw.get("tools", [])
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        raise ToolsRegistryError(f"ツール登録簿を読み込めません: {path}（{e}）") from e
    return ToolsRegistry(tools=tools, allow_online=bool(raw.get("allow_online", True)))


def save_registry(paths: RuntimePaths, registry: ToolsRegistry) -> Path:
    path = tools_json_path(paths)
    data = {
        "schema_version": SCHEMA_VERSION,
        "allow_online": registry.allow_online,
        "tools": [asdict(t) for t in registry.tools],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise ToolsRegistryError(f"ツール登録簿を保存できません（共有サーバが読取専用の可能性があります）: {e}") from e
    return path


def make_tool_id(name: str, existing: set[str]) -> str:
    base = _ID_SAFE_RE.sub("-", name).strip("-.").lower() or "tool"
    candidate, n = base, 2
    while candidate in existing:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def register_tool(paths: RuntimePaths, name: str, source_requirements: Path,
                  description: str = "", copy_to_runtime: bool = True) -> ToolEntry:
    """ツールを登録する。copy_to_runtime=True なら共有ランタイム内へ requirements.txt をコピーして保存する。"""
    name = name.strip()
    if not name:
        raise ToolsRegistryError("ツール名を入力してください。")
    source_requirements = Path(source_requirements)
    if not source_requirements.is_file():
        raise ToolsRegistryError(f"requirements.txt が見つかりません: {source_requirements}")

    registry = load_registry(paths)
    if any(t.name == name for t in registry.tools):
        raise ToolsRegistryError(f"同名のツールが既に登録されています: {name}")
    tool_id = make_tool_id(name, {t.id for t in registry.tools})

    if copy_to_runtime:
        rel = Path("config") / "tools" / tool_id / "requirements.txt"
        dest = paths.root / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_requirements, dest)
        except OSError as e:
            raise ToolsRegistryError(f"requirements.txt を共有ランタイムへ保存できません: {e}") from e
        req_value = rel.as_posix()
    else:
        req_value = str(source_requirements.resolve())

    entry = ToolEntry(id=tool_id, name=name, requirements=req_value, description=description.strip())
    registry.tools.append(entry)
    save_registry(paths, registry)
    return entry


def unregister_tool(paths: RuntimePaths, tool_id: str) -> None:
    """登録簿から外すだけ（requirements.txt 自体は削除しない）。"""
    registry = load_registry(paths)
    registry.tools = [t for t in registry.tools if t.id != tool_id]
    save_registry(paths, registry)
