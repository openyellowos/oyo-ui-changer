"""
oYo UI Changer（libadwaita 版）のテスト共通基盤

  - host の GNOME 設定（dconf）に書き込まないための安全装置
      1. gi を読み込む前に GSETTINGS_BACKEND=memory を設定する
      2. 実際に使われる GSettings backend が memory であることを確かめる（環境変数だけを信用しない）
      3. 外部コマンド（dconf など）の起動を遮断する
     どれかを確認できなければ UnsafeTestEnvironment で止める（テストを実行しない）
  - アプリ本体を GUI を起動せずに読み込む（load_app）
  - 表示文言を英語に固定する（テストのプロセスだけで LANGUAGE=C。読み込み後に翻訳なしを確かめる）
    日本語を確かめるテストは、ns["_translation"] をそのテストの間だけ差し替える

使い方:
    from helpers import load_app
    ns = load_app()            # 既存のスクラッチテストの ns と同じ辞書
    ns["detect_layout"](...)
"""

import ast
import gettext
import os
import subprocess
import sys

# ---- 1. gi より先に memory backend を指定する -------------------------------------------------
# すでに Gio が読み込まれていると、backend が別のものに決まっている可能性がある
if "gi.repository.Gio" in sys.modules:
    raise ImportError("helpers must be imported before gi.repository.Gio (cannot guarantee the memory backend)")
os.environ["GSETTINGS_BACKEND"] = "memory"
# 表示文言は英語で確かめる（gettext は LANGUAGE=C で翻訳を探さない。このテストのプロセスだけの設定）
os.environ["LANGUAGE"] = "C"

from gi.repository import Gio, GLib  # noqa: E402

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = os.path.join(REPO_DIR, "src", "oyo-ui-changer.py")

# アプリ末尾の起動部分（これを除いて読み込む）
LAUNCH_LINES = "app = OyoUiChangerApp()\napp.run()\n"

MEMORY_BACKEND = "GMemorySettingsBackend"
# backend の確認に使う、GNOME 標準のスキーマ（Extension がなくても存在する）
PROBE_SCHEMA = "org.gnome.desktop.wm.preferences"


class UnsafeTestEnvironment(RuntimeError):
    """host の設定を書き換えないことを保証できない。テストを実行してはいけない"""


class BlockedCommand(subprocess.SubprocessError):
    """テスト中に外部コマンドを起動しようとした"""


# ---- 2. backend の確認 -----------------------------------------------------------------------
def _gtype_name(obj):
    return obj.__gtype__.name if obj is not None else None


def ensure_memory_backend():
    """既定の backend と、実際に開いた Gio.Settings の backend がどちらも memory か確かめる"""
    if os.environ.get("GSETTINGS_BACKEND") != "memory":
        raise UnsafeTestEnvironment(f"GSETTINGS_BACKEND is {os.environ.get('GSETTINGS_BACKEND')!r}, not 'memory'")
    default = _gtype_name(Gio.SettingsBackend.get_default())
    if default != MEMORY_BACKEND:
        raise UnsafeTestEnvironment(f"default GSettings backend is {default}, not {MEMORY_BACKEND}")
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(PROBE_SCHEMA, True) if source is not None else None
    if schema is None:
        raise UnsafeTestEnvironment(f"probe schema not found: {PROBE_SCHEMA}")
    # アプリと同じ開き方（backend 指定なし）で開き、実際の backend を確認する
    probe = Gio.Settings.new_full(schema, None, None)
    actual = _gtype_name(probe.props.backend)
    if actual != MEMORY_BACKEND:
        raise UnsafeTestEnvironment(f"Gio.Settings uses {actual}, not {MEMORY_BACKEND}")


# ---- 3. 外部コマンドの遮断 ---------------------------------------------------------------------
# テスト中に起動しようとした外部コマンドの記録（遮断したもの）
blocked_commands = []

_real_popen = subprocess.Popen


def _blocked(*args, **kwargs):
    blocked_commands.append(args[0] if args else kwargs.get("args"))
    raise BlockedCommand(f"external command blocked during tests: {blocked_commands[-1]!r}")


class _BlockedPopen(_real_popen):
    def __init__(self, *args, **kwargs):  # noqa: D401 - 起動前に必ず止める
        _blocked(*args, **kwargs)


def block_external_commands():
    """
    subprocess / os / GLib / Gio からの外部コマンド起動を止める。
    アプリの read_dconf_raw() は SubprocessError を受けて None を返すため、dconf の生の値は読まない
    （判定には使っていない値。host の dconf に依存しないようにする）
    """
    subprocess.Popen = _BlockedPopen
    os.system = _blocked
    os.popen = _blocked
    for name in ("execv", "execve", "execvp", "execvpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
                 "posix_spawn", "posix_spawnp"):
        if hasattr(os, name):
            setattr(os, name, _blocked)
    for name in ("spawn_async", "spawn_async_with_pipes", "spawn_async_with_fds", "spawn_sync",
                 "spawn_command_line_async", "spawn_command_line_sync"):
        if hasattr(GLib, name):
            setattr(GLib, name, _blocked)
    Gio.Subprocess.new = _blocked
    Gio.SubprocessLauncher.spawnv = _blocked


def host_dconf_dump():
    """host の dconf 全体を読む（読み取りのみ。遮断の対象外）。テスト前後の比較用"""
    proc = _real_popen(["dconf", "dump", "/"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate(timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"dconf dump failed: {err.strip()}")
    return out


# ---- アプリの読み込み ---------------------------------------------------------------------------
# モジュールの最上位で許す文（定義・import・代入と gi.require_version だけ）
_ALLOWED_TOP_LEVEL = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.ClassDef)


def _is_allowed_expr(node):
    if not isinstance(node, ast.Expr):
        return False
    value = node.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):  # docstring
        return True
    func = value.func if isinstance(value, ast.Call) else None
    return (isinstance(func, ast.Attribute) and func.attr == "require_version"
            and isinstance(func.value, ast.Name) and func.value.id == "gi")


def _check_top_level(tree, path):
    """起動部分を除いたあと、読み込むだけで何かを実行する文が残っていないか確かめる"""
    for node in tree.body:
        if isinstance(node, _ALLOWED_TOP_LEVEL) or _is_allowed_expr(node):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == "OyoUiChangerApp":
                    raise UnsafeTestEnvironment(f"{path}:{node.lineno}: application is created at top level")
            continue
        raise UnsafeTestEnvironment(f"{path}:{node.lineno}: unexpected top-level statement ({type(node).__name__})")


def load_app(path=APP_PATH):
    """
    アプリ本体を GUI を起動せずに読み込み、名前空間（dict）を返す。
    起動部分が見つからない・ほかに実行される文がある・memory backend でない場合は UnsafeTestEnvironment
    """
    ensure_memory_backend()
    block_external_commands()

    with open(path, encoding="utf-8") as f:
        src = f.read()
    if src.count(LAUNCH_LINES) != 1 or not src.endswith(LAUNCH_LINES):
        raise UnsafeTestEnvironment(f"{path}: launch lines not found exactly once at the end of the file")
    src = src[: -len(LAUNCH_LINES)]

    tree = ast.parse(src, filename=path)
    _check_top_level(tree, path)

    ns = {"__name__": "oyo_ui_changer_under_test", "__file__": path}
    exec(compile(tree, path, "exec"), ns)

    # 読み込みで backend が変わっていないこと、アプリが作られていないことを確かめる
    ensure_memory_backend()
    if "app" in ns:
        raise UnsafeTestEnvironment("application object was created while loading")
    # 翻訳が読み込まれていない（英語のまま）ことを確かめる
    if type(ns.get("_translation")) is not gettext.NullTranslations:
        raise RuntimeError(f"tests must run without translations, got {type(ns.get('_translation')).__name__}")
    return ns
