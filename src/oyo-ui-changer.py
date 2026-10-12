#!/usr/bin/env python3

import gettext
import json
import math
import os
import shutil
import subprocess
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk


#----------------------------------------------------------------------------------------------------------------
# 表示文言の翻訳（gettext）
#   - 翻訳するのは画面に出す文言だけ（アプリ ID、レイアウト ID、GSettings のキーと値、Extension 名、ログは翻訳しない）
#   - 言語は gettext の標準どおり LANGUAGE → LC_ALL → LC_MESSAGES → LANG で決まり、翻訳がなければ英語のまま
#   - 翻訳は使う時点で _() を呼んで行う（定数には N_() で印だけを付ける）。差し込みは名前付きの {name} を使う
#----------------------------------------------------------------------------------------------------------------
GETTEXT_DOMAIN = "oyo-ui-changer"


def find_localedir():
    """インストール先では /usr/bin から見た ../share/locale。なければ None（gettext の既定の場所）"""
    path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "share", "locale"))
    return path if os.path.isdir(path) else None


_translation = gettext.translation(GETTEXT_DOMAIN, localedir=find_localedir(), fallback=True)


def _(message):
    """表示文言を翻訳する（翻訳がなければ英語のまま）"""
    return _translation.gettext(message)


def N_(message):
    """翻訳対象の印だけを付ける（翻訳は使う時点で _() を呼んで行う）"""
    return message


#----------------------------------------------------------------------------------------------------------------
# 現在の設定の読み取り（read-only）
#   - Gio.Settings で読むだけで、set / reset / dconf write は行わない
#   - Extension のスキーマは、GNOME Shell と同じく
#     「ユーザーの拡張機能 → システムの拡張機能」の schemas/ を優先し、なければ標準のスキーマを使う
#   - 読めないものは例外にせず None にする
#----------------------------------------------------------------------------------------------------------------
STATE_SPEC = (
    # (名前, スキーマID, Extension UUID（なければ None）, 読むキー)
    ("shell", "org.gnome.shell", None, (
        "enabled-extensions",
        "disabled-extensions",
        "disable-user-extensions",
    )),
    ("wm", "org.gnome.desktop.wm.preferences", None, (
        "button-layout",
    )),
    ("dash-to-dock", "org.gnome.shell.extensions.dash-to-dock", "dash-to-dock@micxgx.gmail.com", (
        "dock-position",
        "dock-fixed",
        "extend-height",
        "dash-max-icon-size",
        "show-apps-at-top",
        "click-action",
        "running-indicator-style",
        "transparency-mode",
    )),
    ("dash-to-panel", "org.gnome.shell.extensions.dash-to-panel", "dash-to-panel@jderose9.github.com", (
        "panel-positions",
        "panel-sizes",
        "panel-element-positions",
        "stockgs-keep-dash",
    )),
    ("arcmenu", "org.gnome.shell.extensions.arcmenu", "arcmenu@arcmenu.com", (
        "menu-layout",
        "position-in-panel",
    )),
)


def extension_dirs(uuid):
    """GNOME Shell の探索順（ユーザー → システム）で、存在する Extension のディレクトリを返す"""
    data_dirs = [GLib.get_user_data_dir()] + list(GLib.get_system_data_dirs())
    dirs = []
    for base in data_dirs:
        path = os.path.join(base, "gnome-shell", "extensions", uuid)
        if os.path.isdir(path):
            dirs.append(path)
    return dirs


def lookup_schema(schema_id, uuid):
    """スキーマを探して (schema, 見つかった場所) を返す。見つからなければ (None, None)"""
    default_source = Gio.SettingsSchemaSource.get_default()

    if uuid:
        for ext_dir in extension_dirs(uuid):
            schema_dir = os.path.join(ext_dir, "schemas")
            if not os.path.isfile(os.path.join(schema_dir, "gschemas.compiled")):
                continue
            try:
                source = Gio.SettingsSchemaSource.new_from_directory(schema_dir, default_source, False)
            except GLib.Error:
                continue
            schema = source.lookup(schema_id, False)
            if schema is not None:
                return schema, schema_dir

    if default_source is not None:
        schema = default_source.lookup(schema_id, True)
        if schema is not None:
            return schema, "default"

    return None, None


def read_dconf_raw(path):
    """dconf に実際に保存されている値を文字列のまま読む（型の誤りの確認用）。読めなければ None"""
    if not path or not shutil.which("dconf"):
        return None
    try:
        result = subprocess.run(["dconf", "read", path], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def read_current_state():
    """
    現在の GNOME / Extension の設定を読み取って辞書で返す。
      state[名前] = {
          "schema": スキーマID, "uuid": UUID, "installed": [Extension のディレクトリ],
          "schema_source": スキーマの場所（"default" / ディレクトリ / None）,
          "keys": { キー: {"value": GSettings として読んだ値, "raw": dconf に保存された文字列} },
      }
    """
    state = {}
    for name, schema_id, uuid, keys in STATE_SPEC:
        entry = {
            "schema": schema_id,
            "uuid": uuid,
            "installed": extension_dirs(uuid) if uuid else None,
            "schema_source": None,
            "keys": {key: {"value": None, "raw": None} for key in keys},
        }
        state[name] = entry

        try:
            schema, schema_source = lookup_schema(schema_id, uuid)
        except GLib.Error:
            schema, schema_source = None, None
        if schema is None:
            continue
        entry["schema_source"] = schema_source

        settings = Gio.Settings.new_full(schema, None, None)
        settings_path = schema.get_path()
        for key in keys:
            # 存在しないキーを get_value() するとプロセスが止まるため、必ず先に確認する
            if not schema.has_key(key):
                continue
            try:
                entry["keys"][key]["value"] = settings.get_value(key).unpack()
            except (GLib.Error, TypeError, ValueError):
                pass
            if settings_path:
                entry["keys"][key]["raw"] = read_dconf_raw(settings_path + key)

    return state


def print_state(state):
    """read_current_state() の結果を、確認用にコンソールへ出力する"""
    print("=== current GNOME state (read-only) ===")
    for name, entry in state.items():
        print(f"[{name}] schema={entry['schema']}")
        if entry["uuid"]:
            print(f"  installed: {entry['installed'] or 'not found'}")
        print(f"  schema source: {entry['schema_source'] or 'Unknown (schema not found)'}")
        for key, item in entry["keys"].items():
            value = "Unknown" if item["value"] is None else repr(item["value"])
            raw = "(not set in dconf)" if item["raw"] is None else item["raw"]
            print(f"  {key} = {value}")
            print(f"      dconf: {raw}")


#----------------------------------------------------------------------------------------------------------------
# 現在のレイアウトの判定
#   - 構造を決める主要キーだけで判定し、細かな調整（サイズ、ArcMenu の形、button-layout など）は見ない
#   - dconf の生の値は使わず、read_current_state() の "value" だけを使う
#   - 判定に必要な値が分からない、またはどれにも一致しない場合は custom
#----------------------------------------------------------------------------------------------------------------
LAYOUT_ORIGINAL = "original"
LAYOUT_WINDOWS10 = "windows10"
LAYOUT_WINDOWS11 = "windows11"
LAYOUT_MACOS = "macos"
LAYOUT_CUSTOM = "custom"

MIXED = "mixed"

# dash-to-panel の既定値（panelPositions.js / panelSettings.js）
DTP_DEFAULT_POSITION = "BOTTOM"
DTP_DEFAULT_TASKBAR = ("stackedTL", True)


def state_value(state, name, key):
    try:
        return state[name]["keys"][key]["value"]
    except (KeyError, TypeError):
        return None


def extension_enabled(state, name):
    """Extension が有効なら True、無効なら False、判断できなければ None"""
    enabled = state_value(state, "shell", "enabled-extensions")
    disabled = state_value(state, "shell", "disabled-extensions")
    disable_user = state_value(state, "shell", "disable-user-extensions")
    entry = state.get(name) or {}
    uuid = entry.get("uuid")
    if uuid is None or enabled is None or disabled is None or disable_user is None:
        return None
    if not entry.get("installed"):
        return False
    return uuid in enabled and uuid not in disabled and not disable_user


def monitor_values(json_text):
    """モニターごとの JSON（文字列）を辞書にする。読めなければ None"""
    if not isinstance(json_text, str):
        return None
    try:
        values = json.loads(json_text)
    except ValueError:
        return None
    return values if isinstance(values, dict) else None


def same_for_all_monitors(values):
    """全モニターで同じなら その値、違えば MIXED"""
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else MIXED


def panel_position(state):
    """dash-to-panel の位置（全モニター共通）。MIXED / None もありうる"""
    values = monitor_values(state_value(state, "dash-to-panel", "panel-positions"))
    if values is None:
        return None
    if not values:
        return DTP_DEFAULT_POSITION
    return same_for_all_monitors(values.values())


def taskbar_placement(state):
    """dash-to-panel のタスクバーの (position, visible)（全モニター共通）。MIXED / None もありうる"""
    values = monitor_values(state_value(state, "dash-to-panel", "panel-element-positions"))
    if values is None:
        return None
    if not values:
        return DTP_DEFAULT_TASKBAR

    placements = []
    for elements in values.values():
        if not isinstance(elements, list):
            return None
        taskbar = next((e for e in elements if isinstance(e, dict) and e.get("element") == "taskbar"), None)
        if taskbar is None:
            return None
        placements.append((taskbar.get("position"), taskbar.get("visible", True) is not False))
    return same_for_all_monitors(placements)


def layout_facts(state):
    """判定に使う値をまとめる（確認用の表示にも使う）"""
    return {
        "dock_enabled": extension_enabled(state, "dash-to-dock"),
        "panel_enabled": extension_enabled(state, "dash-to-panel"),
        "dock_position": state_value(state, "dash-to-dock", "dock-position"),
        "panel_position": panel_position(state),
        "taskbar": taskbar_placement(state),
    }


def detect_layout(state):
    """現在の状態から original / windows10 / windows11 / macos / custom のいずれかを返す"""
    facts = layout_facts(state)
    dock = facts["dock_enabled"]
    panel = facts["panel_enabled"]

    if dock is None or panel is None:
        return LAYOUT_CUSTOM

    if dock and not panel:
        return LAYOUT_ORIGINAL if facts["dock_position"] == "LEFT" else LAYOUT_CUSTOM

    if panel and not dock:
        if facts["panel_position"] != "BOTTOM":
            return LAYOUT_CUSTOM
        taskbar = facts["taskbar"]
        if not isinstance(taskbar, tuple):
            return LAYOUT_CUSTOM
        position, visible = taskbar
        if not visible:
            return LAYOUT_CUSTOM
        if position == "stackedTL":
            return LAYOUT_WINDOWS10
        if position in ("centered", "centerMonitor"):
            return LAYOUT_WINDOWS11
        return LAYOUT_CUSTOM

    if panel and dock:
        if facts["panel_position"] == "TOP" and facts["dock_position"] == "BOTTOM":
            return LAYOUT_MACOS
        return LAYOUT_CUSTOM

    return LAYOUT_CUSTOM


#----------------------------------------------------------------------------------------------------------------
# レイアウトの適用（oYo Original / Windows 10 / Windows 11 / macOS）
#   - 書き込むのは、目標値と今の値が違うキーだけ
#   - Extension の一覧は、管理対象（dash-to-dock / dash-to-panel / arcmenu）だけを出し入れし、
#     ほかの Extension は順番も含めてそのまま残す
#   - disable-user-extensions は変更しない
#   - 流れ: plan_layout()（事前確認と変更点の計算。書き込みなし）→ apply_plan()（書き込み・失敗時は rollback）
#----------------------------------------------------------------------------------------------------------------
DOCK_UUID = "dash-to-dock@micxgx.gmail.com"
PANEL_UUID = "dash-to-panel@jderose9.github.com"
ARCMENU_UUID = "arcmenu@arcmenu.com"

DOCK_SCHEMA = "org.gnome.shell.extensions.dash-to-dock"
PANEL_SCHEMA = "org.gnome.shell.extensions.dash-to-panel"
ARCMENU_SCHEMA = "org.gnome.shell.extensions.arcmenu"
WM_SCHEMA = "org.gnome.desktop.wm.preferences"
SHELL_SCHEMA = "org.gnome.shell"

MSG_USER_EXTENSIONS_DISABLED = N_(
    "User extensions are disabled. Enable GNOME Shell extensions before applying this layout."
)
# Apply に失敗し、さらに一部の設定を元に戻せなかったときの消えない警告（復旧を保証しない表現にする）
MSG_ROLLBACK_INCOMPLETE = N_(
    "The layout could not be applied, and some settings could not be restored. "
    "Your desktop may remain partly changed. Selecting a layout and applying it again may help."
)
# 想定外の例外で Apply できなかったとき（例外の中身は画面に出さず、ログに残す）
MSG_UNEXPECTED_APPLY_ERROR = N_("The layout could not be applied because of an unexpected error.")
# 表示の読み直し（現在のレイアウトの再確認）に失敗したとき
MSG_LAYOUT_CHECK_FAILED = N_("The current layout could not be checked. The display may not match your desktop.")

# dash-to-panel の panel-* が空のときに使う鍵（1台目のモニター。dash-to-panel が後でモニター ID に置き換える）
PANEL_FALLBACK_MONITOR = "0"

ORIGINAL_DOCK_SETTINGS = {
    "dock-position": GLib.Variant("s", "LEFT"),
    "dock-fixed": GLib.Variant("b", True),
    "extend-height": GLib.Variant("b", True),
    "dash-max-icon-size": GLib.Variant("i", 32),
    "custom-theme-shrink": GLib.Variant("b", True),
    "running-indicator-style": GLib.Variant("s", "DOTS"),
    "transparency-mode": GLib.Variant("s", "DYNAMIC"),
    "click-action": GLib.Variant("s", "minimize"),
    "show-apps-at-top": GLib.Variant("b", False),
}
ORIGINAL_WM_SETTINGS = {
    "button-layout": GLib.Variant("s", "appmenu:minimize,maximize,close"),
}

# Windows 10 / 11 で共通のパネル（下・幅いっぱい）
WINDOWS_PANEL_POSITION = "BOTTOM"
WINDOWS_PANEL_SIZE = 36
WINDOWS_PANEL_LENGTH = 100
WINDOWS_WM_SETTINGS = ORIGINAL_WM_SETTINGS
# macOS から戻ったときに Overview の dash が残らないよう、Windows では false にそろえる
WINDOWS_PANEL_EXTRA_SETTINGS = {
    "stockgs-keep-dash": GLib.Variant("b", False),
}

# dash-to-panel は一覧にある要素だけを並べるため、9 要素すべてを書く
WINDOWS10_ELEMENTS = [
    {"element": "showAppsButton", "visible": False, "position": "stackedTL"},
    {"element": "activitiesButton", "visible": False, "position": "stackedTL"},
    {"element": "leftBox", "visible": True, "position": "stackedTL"},
    {"element": "taskbar", "visible": True, "position": "stackedTL"},
    {"element": "centerBox", "visible": True, "position": "stackedBR"},
    {"element": "rightBox", "visible": True, "position": "stackedBR"},
    {"element": "dateMenu", "visible": True, "position": "stackedBR"},
    {"element": "systemMenu", "visible": True, "position": "stackedBR"},
    {"element": "desktopButton", "visible": True, "position": "stackedBR"},
]
# centerBox（ArcMenu のボタン）→ taskbar を連続させ、両方を centerMonitor にして
# 「スタートボタン → アプリ」を 1 つのまとまりとして画面の中央に置く
WINDOWS11_ELEMENTS = [
    {"element": "showAppsButton", "visible": False, "position": "stackedTL"},
    {"element": "activitiesButton", "visible": False, "position": "stackedTL"},
    {"element": "leftBox", "visible": True, "position": "stackedTL"},
    {"element": "centerBox", "visible": True, "position": "centerMonitor"},
    {"element": "taskbar", "visible": True, "position": "centerMonitor"},
    {"element": "rightBox", "visible": True, "position": "stackedBR"},
    {"element": "dateMenu", "visible": True, "position": "stackedBR"},
    {"element": "systemMenu", "visible": True, "position": "stackedBR"},
    {"element": "desktopButton", "visible": True, "position": "stackedBR"},
]

# macOS: 上部のパネル（ArcMenu・時計・システムメニュー）＋ 下部中央の Dock
MACOS_PANEL_POSITION = "TOP"
MACOS_PANEL_SIZE = 32
MACOS_PANEL_LENGTH = 100
# タスクバーは非表示（アプリは Dock に置く）。ArcMenu は leftBox（左端）
MACOS_ELEMENTS = [
    {"element": "showAppsButton", "visible": False, "position": "stackedTL"},
    {"element": "activitiesButton", "visible": False, "position": "stackedTL"},
    {"element": "leftBox", "visible": True, "position": "stackedTL"},
    {"element": "taskbar", "visible": False, "position": "stackedTL"},
    {"element": "centerBox", "visible": True, "position": "stackedBR"},
    {"element": "rightBox", "visible": True, "position": "stackedBR"},
    {"element": "dateMenu", "visible": True, "position": "stackedBR"},
    {"element": "systemMenu", "visible": True, "position": "stackedBR"},
    {"element": "desktopButton", "visible": False, "position": "stackedBR"},
]
# dash-to-dock は Overview の dash を自分の Dock に差し替えるため、
# stockgs-keep-dash=false のままだと dash-to-panel が Dock を隠してしまう
MACOS_PANEL_EXTRA_SETTINGS = {
    "stockgs-keep-dash": GLib.Variant("b", True),
}
MACOS_DOCK_SETTINGS = {
    "dock-position": GLib.Variant("s", "BOTTOM"),
    "extend-height": GLib.Variant("b", False),
    "dash-max-icon-size": GLib.Variant("i", 38),
    "show-apps-at-top": GLib.Variant("b", True),
    "dock-fixed": GLib.Variant("b", True),
    "custom-theme-shrink": GLib.Variant("b", True),
    "running-indicator-style": GLib.Variant("s", "DOTS"),
    "transparency-mode": GLib.Variant("s", "DYNAMIC"),
    "click-action": GLib.Variant("s", "minimize"),
}
MACOS_WM_SETTINGS = {
    "button-layout": GLib.Variant("s", "close,minimize,maximize:appmenu"),
}

# ArcMenu 固有の値（UI Changer のレイアウト ID とは別物。ここだけで対応づける）
ARCMENU_LAYOUT = {
    LAYOUT_WINDOWS10: "windows",
    LAYOUT_WINDOWS11: "11",
    LAYOUT_MACOS: "brisk",
}
# ArcMenu のボタンを置くパネルの領域（Left → leftBox、Center → centerBox）
ARCMENU_POSITION = {
    LAYOUT_WINDOWS10: "Left",
    LAYOUT_WINDOWS11: "Center",
    LAYOUT_MACOS: "Left",
}
# メニュー本体を出す場所（Off: ボタンの真上、BottomCentered: パネルの真上・画面の中央）
ARCMENU_MENU_LOCATION = {
    LAYOUT_WINDOWS10: "Off",
    LAYOUT_WINDOWS11: "BottomCentered",
    LAYOUT_MACOS: "Off",
}


def arcmenu_settings(layout_id):
    return {
        "menu-layout": GLib.Variant("s", ARCMENU_LAYOUT[layout_id]),
        "position-in-panel": GLib.Variant("s", ARCMENU_POSITION[layout_id]),
        "dash-to-panel-standalone": GLib.Variant("b", False),
        "force-menu-location": GLib.Variant("s", ARCMENU_MENU_LOCATION[layout_id]),
    }


class ApplyError(Exception):
    """適用できなかった理由（ユーザーに表示する文）を持つ例外。事前確認の失敗（何も書いていない）"""


class ApplyWriteError(ApplyError):
    """書き込みの途中で失敗した（元の値に戻したあと）"""


class ApplyRollbackError(ApplyWriteError):
    """
    書き込みの途中で失敗し、さらに元に戻せなかった（または戻ったことを確かめられなかった）設定がある。
    メッセージは元の失敗のまま。failed は戻せなかった [(スキーマ ID, キー), ...]、元の失敗は __cause__
    """

    def __init__(self, message, failed):
        super().__init__(message)
        self.failed = list(failed)


def open_settings(schema_id, uuid=None):
    schema, _source = lookup_schema(schema_id, uuid)
    if schema is None:
        raise ApplyError(_("Settings schema not found: {schema}").format(schema=schema_id))
    return Gio.Settings.new_full(schema, None, None), schema


def require_installed(uuid, name):
    if not extension_dirs(uuid):
        raise ApplyError(_("{name} is not installed.").format(name=name))


def check_targets(settings, schema, targets):
    """キーの存在・書き込み可否・値の範囲を確認し、今の値と違うキーだけを返す（書き込みはしない）"""
    changes = []
    for key, value in targets.items():
        if not schema.has_key(key):
            raise ApplyError(_("Setting not found: {schema} {key}").format(schema=schema.get_id(), key=key))
        if not settings.is_writable(key):
            raise ApplyError(_("Setting is not writable: {schema} {key}").format(schema=schema.get_id(), key=key))
        if not schema.get_key(key).range_check(value):
            raise ApplyError(_("Invalid value for {schema} {key}").format(schema=schema.get_id(), key=key))
        if not settings.get_value(key).equal(value):
            changes.append((key, value))
    return changes


def open_shell():
    """org.gnome.shell を開き、Extension を切り替えられる状態か確認する"""
    shell, shell_schema = open_settings(SHELL_SCHEMA)
    for key in ("enabled-extensions", "disabled-extensions", "disable-user-extensions"):
        if not shell_schema.has_key(key):
            raise ApplyError(_("Setting not found: {schema} {key}").format(schema=SHELL_SCHEMA, key=key))
    if shell.get_boolean("disable-user-extensions"):
        raise ApplyError(_(MSG_USER_EXTENSIONS_DISABLED))
    return shell, shell_schema


def extension_targets(shell, enable, disable):
    """
    Extension の一覧の目標値。
      enabled : disable を外し、enable のうち無いものを末尾に順に加える（ほかは順番も含めて保持）
      disabled: enable を外すだけ（ほかは保持。新たに加えるものはない）
    """
    enabled = shell.get_strv("enabled-extensions")
    disabled = shell.get_strv("disabled-extensions")
    new_enabled = [uuid for uuid in enabled if uuid not in disable]
    for uuid in enable:
        if uuid not in new_enabled:
            new_enabled.append(uuid)
    new_disabled = [uuid for uuid in disabled if uuid not in enable]
    return {
        "enabled-extensions": GLib.Variant("as", new_enabled),
        "disabled-extensions": GLib.Variant("as", new_disabled),
    }


def read_monitor_json(settings, key):
    """dash-to-panel のモニターごとの JSON を読む。読めなければ ApplyError（知らないデータを壊さないため）"""
    values = monitor_values(settings.get_string(key))
    if values is None:
        raise ApplyError(_("Could not read dash-to-panel setting: {key}").format(key=key))
    return values


def monitor_json_target(current, value_for):
    """既存の全モニターを value_for(今の値) にそろえる。空なら PANEL_FALLBACK_MONITOR だけを作る"""
    if current:
        new = {monitor: value_for(value) for monitor, value in current.items()}
    else:
        new = {PANEL_FALLBACK_MONITOR: value_for(None)}
    return new


def to_json_variant(values):
    # dash-to-panel（JSON.stringify）と同じ、空白なしの形で書く
    return GLib.Variant("s", json.dumps(values, separators=(",", ":")))


def plan_original():
    """
    oYo Original にするための変更を調べる（書き込みはしない）。
    事前確認に失敗したら ApplyError。戻り値は [(settings, [(key, value), ...]), ...]（書く順）
    """
    require_installed(DOCK_UUID, "Dash to Dock")

    shell, shell_schema = open_shell()
    dock, dock_schema = open_settings(DOCK_SCHEMA, DOCK_UUID)
    wm, wm_schema = open_settings(WM_SCHEMA)

    shell_targets = extension_targets(shell, enable=(DOCK_UUID,), disable=(PANEL_UUID, ARCMENU_UUID))

    # 先に全部を確認し、1つでも問題があれば何も書かない
    dock_changes = check_targets(dock, dock_schema, ORIGINAL_DOCK_SETTINGS)
    wm_changes = check_targets(wm, wm_schema, ORIGINAL_WM_SETTINGS)
    shell_changes = check_targets(shell, shell_schema, shell_targets)

    # 書く順: Dock の設定 → ボタンの配置 → Extension の一覧（Dock が設定済みの状態で現れるように最後）
    return [(dock, dock_changes), (wm, wm_changes), (shell, shell_changes)]


def plan_panel_layout(elements_value, arcmenu_targets, *,
                      position=WINDOWS_PANEL_POSITION, size=WINDOWS_PANEL_SIZE, length=WINDOWS_PANEL_LENGTH,
                      panel_extra_targets=WINDOWS_PANEL_EXTRA_SETTINGS, wm_targets=WINDOWS_WM_SETTINGS,
                      dock_targets=None, enable=(PANEL_UUID, ARCMENU_UUID), disable=(DOCK_UUID,)):
    """
    dash-to-panel ＋ ArcMenu を使うレイアウト（Windows 10 / 11、macOS）の変更を調べる（書き込みはしない）。
    引数の既定値は Windows 10 / 11 の値。macOS は位置・大きさ・追加設定・ボタン配置・Dock・Extension を渡す。
    dock_targets が None なら dash-to-dock の設定には触れない。
    戻り値は plan_original() と同じ形
    """
    require_installed(PANEL_UUID, "Dash to Panel")
    require_installed(ARCMENU_UUID, "ArcMenu")
    if dock_targets is not None:
        require_installed(DOCK_UUID, "Dash to Dock")

    shell, shell_schema = open_shell()
    panel, panel_schema = open_settings(PANEL_SCHEMA, PANEL_UUID)
    arcmenu, arcmenu_schema = open_settings(ARCMENU_SCHEMA, ARCMENU_UUID)
    wm, wm_schema = open_settings(WM_SCHEMA)

    for key in ("panel-positions", "panel-sizes", "panel-element-positions", "panel-lengths"):
        if not panel_schema.has_key(key):
            raise ApplyError(_("Setting not found: {schema} {key}").format(schema=PANEL_SCHEMA, key=key))

    # panel-* は、今の値と中身が違うときだけ目標に入れる（JSON の書式の違いだけでは書かない）
    panel_targets = {}
    positions = read_monitor_json(panel, "panel-positions")
    sizes = read_monitor_json(panel, "panel-sizes")
    elements = read_monitor_json(panel, "panel-element-positions")
    lengths = read_monitor_json(panel, "panel-lengths")
    for key, current, value_for in (
        ("panel-positions", positions, lambda _v: position),
        ("panel-sizes", sizes, lambda _v: size),
        ("panel-element-positions", elements, lambda _v: elements_value),
    ):
        new = monitor_json_target(current, value_for)
        if new != current:
            panel_targets[key] = to_json_variant(new)
    # panel-lengths は、空なら既定（100）のままにし、100 以外があるときだけ 100 にそろえる
    if lengths:
        new_lengths = {monitor: length for monitor in lengths}
        if new_lengths != lengths:
            panel_targets["panel-lengths"] = to_json_variant(new_lengths)
    panel_targets.update(panel_extra_targets)

    shell_targets = extension_targets(shell, enable=enable, disable=disable)

    # 先に全部を確認し、1つでも問題があれば何も書かない
    plan = []
    if dock_targets is not None:
        dock, dock_schema = open_settings(DOCK_SCHEMA, DOCK_UUID)
        plan.append((dock, check_targets(dock, dock_schema, dock_targets)))
    plan.append((panel, check_targets(panel, panel_schema, panel_targets)))
    plan.append((arcmenu, check_targets(arcmenu, arcmenu_schema, arcmenu_targets)))
    plan.append((wm, check_targets(wm, wm_schema, wm_targets)))
    plan.append((shell, check_targets(shell, shell_schema, shell_targets)))

    # 書く順: Dock → パネル → ArcMenu → ボタンの配置 → Extension の一覧
    # （Extension の一覧を最後にして、設定済みの状態で切り替わるようにする）
    return plan


def plan_windows10():
    return plan_panel_layout(WINDOWS10_ELEMENTS, arcmenu_settings(LAYOUT_WINDOWS10))


def plan_windows11():
    return plan_panel_layout(WINDOWS11_ELEMENTS, arcmenu_settings(LAYOUT_WINDOWS11))


def plan_macos():
    return plan_panel_layout(
        MACOS_ELEMENTS, arcmenu_settings(LAYOUT_MACOS),
        position=MACOS_PANEL_POSITION, size=MACOS_PANEL_SIZE, length=MACOS_PANEL_LENGTH,
        panel_extra_targets=MACOS_PANEL_EXTRA_SETTINGS, wm_targets=MACOS_WM_SETTINGS,
        dock_targets=MACOS_DOCK_SETTINGS,
        enable=(PANEL_UUID, ARCMENU_UUID, DOCK_UUID), disable=(),
    )


LAYOUT_PLANNERS = {
    LAYOUT_ORIGINAL: plan_original,
    LAYOUT_WINDOWS10: plan_windows10,
    LAYOUT_WINDOWS11: plan_windows11,
    LAYOUT_MACOS: plan_macos,
}


def plan_layout(layout_id):
    planner = LAYOUT_PLANNERS.get(layout_id)
    if planner is None:
        raise ApplyError(_("Not implemented yet."))
    return planner()


def confirm_layout(candidate):
    """
    detect_layout() の候補が、そのレイアウトの管理対象の設定と完全に一致しているか確かめる（書き込みはしない）。
    候補の plan_layout() の変更予定が 0 件なら候補を、1 件以上・計画を作れない・候補が custom / 不明なら custom を返す。
    ほかのレイアウトは調べない
    """
    if candidate not in LAYOUT_PLANNERS:
        return LAYOUT_CUSTOM
    try:
        plan = plan_layout(candidate)
    except Exception:  # 事前確認の失敗（ApplyError）も想定外の例外も、一致を確かめられないので custom
        return LAYOUT_CUSTOM
    if any(changes for _settings, changes in plan):
        return LAYOUT_CUSTOM
    return candidate


def rollback(written):
    """
    記録した元のユーザー値に戻す。元にユーザー値がなかったキーは reset() する。
    戻せなかった・戻ったことを確かめられなかったキーを [(スキーマ ID, キー), ...] で返す（全部戻れば空）。
    1 つのキーで失敗しても、残りのキーは戻し続ける。失敗の理由はログに出す
    """
    failed = []

    def fail(settings, key, reason):
        item = (settings.props.schema_id, key)
        print(f"rollback failed: {item[0]} {key}: {reason}")
        if item not in failed:
            failed.append(item)

    touched = []
    for settings, key, old_user_value in reversed(written):
        try:
            if old_user_value is None:
                settings.reset(key)
            elif not settings.set_value(key, old_user_value):
                fail(settings, key, "write rejected")
        except Exception as error:  # 戻せなかったキーがあっても、残りは戻す
            fail(settings, key, error)
        if settings not in touched:
            touched.append(settings)
    # delay() した Gio.Settings は delay-apply モードのままなので、apply() しないと反映されない
    for settings in touched:
        try:
            settings.apply()
        except Exception as error:  # 反映できなかった schema のキーは、戻ったことを確かめられない
            for written_settings, key, _old in written:
                if written_settings is settings:
                    fail(settings, key, f"apply failed: {error}")
    try:
        Gio.Settings.sync()
    except Exception as error:  # 保存を確かめられないので、全部を確かめられなかったとする
        for settings, key, _old in written:
            fail(settings, key, f"sync failed: {error}")
    # 読み直して、元の状態（ユーザー値の有無と値）に戻ったか確かめる
    for settings, key, old_user_value in written:
        try:
            current = settings.get_user_value(key)
        except Exception as error:
            fail(settings, key, f"could not read back: {error}")
            continue
        if old_user_value is None:
            restored = current is None
        else:
            restored = current is not None and current.equal(old_user_value)
        if not restored:
            fail(settings, key, f"not restored (now {None if current is None else current.print_(False)})")
    return failed


def apply_plan(plan):
    """plan_layout() の結果を書き込む。途中で失敗したら元に戻して ApplyWriteError"""
    written = []
    try:
        for settings, changes in plan:
            if not changes:
                continue
            # 1つの schema の変更は delay() / apply() でまとめて書く
            old_values = [(settings, key, settings.get_user_value(key)) for key, _value in changes]
            settings.delay()
            try:
                for key, value in changes:
                    if not settings.set_value(key, value):
                        raise ApplyWriteError(_("Failed to write {key}").format(key=key))
                settings.apply()
            except Exception:
                # まだ反映していない変更は捨てる（反映済みの schema は rollback で戻す）
                settings.revert()
                raise
            written.extend(old_values)
        Gio.Settings.sync()
    except Exception as error:
        try:
            failed = rollback(written)
        except Exception as rollback_error:  # rollback 自体が想定外に失敗しても、元の失敗を失わない
            print(f"rollback failed: {rollback_error}")
            failed = list(dict.fromkeys((settings.props.schema_id, key) for settings, key, _old in written))
        if isinstance(error, ApplyWriteError):
            message = str(error)
        else:
            message = _("Failed to apply the layout: {error}").format(error=error)
        if failed:
            raise ApplyRollbackError(message, failed) from error
        if isinstance(error, ApplyWriteError):
            raise
        raise ApplyWriteError(message) from error
    return [(settings.props.schema_id, key) for settings, key, _old in written]


def apply_layout(layout_id):
    """レイアウトを適用し、書いたキーの一覧を返す。適用できなければ ApplyError"""
    return apply_plan(plan_layout(layout_id))


CSS = """
.layout-card {
    padding: 12px;
}
.layout-card:checked {
    background-color: alpha(@accent_bg_color, 0.15);
    box-shadow: inset 0 0 0 2px @accent_color;
}
.layout-card .layout-check {
    color: @accent_color;
}
.layout-card .current-badge {
    padding: 1px 8px;
    border-radius: 999px;
    background-color: alpha(currentColor, 0.1);
    font-weight: bold;
}
"""


#----------------------------------------------------------------------------------------------------------------
# プレビュー（仮の図形）
#   後で本物のイラストに差し替えるときは、create_preview() で Gtk.Picture を返すように変える
#----------------------------------------------------------------------------------------------------------------
def rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def fill(cr, color, alpha, x, y, w, h, r=2):
    cr.set_source_rgba(color.red, color.green, color.blue, alpha)
    rounded_rect(cr, x, y, w, h, r)
    cr.fill()


def draw_icons(cr, color, count, x, y, size, gap, vertical=False):
    for i in range(count):
        offset = i * (size + gap)
        if vertical:
            fill(cr, color, 0.75, x, y + offset, size, size, 1.5)
        else:
            fill(cr, color, 0.75, x + offset, y, size, size, 1.5)


def draw_layout_preview(area, cr, width, height, layout_id):
    color = area.get_color()

    # 画面の枠（16:10）
    sw = min(width, height * 1.6)
    sh = sw / 1.6
    sx = (width - sw) / 2
    sy = (height - sh) / 2
    fill(cr, color, 0.08, sx, sy, sw, sh, 6)

    top_h = sh * 0.07
    icon = sh * 0.08
    gap = icon * 0.5

    if layout_id == LAYOUT_ORIGINAL:
        # 上部バー＋左側に固定した縦長の Dock
        fill(cr, color, 0.30, sx, sy, sw, top_h, 2)
        dock_w = icon * 1.8
        fill(cr, color, 0.40, sx, sy + top_h, dock_w, sh - top_h, 2)
        draw_icons(cr, color, 5, sx + (dock_w - icon) / 2, sy + top_h + gap, icon, gap, vertical=True)

    elif layout_id == LAYOUT_WINDOWS10:
        # 下部のタスクバー（スタートと左寄せのアイコン）
        bar_h = icon * 1.8
        fill(cr, color, 0.40, sx, sy + sh - bar_h, sw, bar_h, 2)
        draw_icons(cr, color, 5, sx + gap, sy + sh - bar_h + (bar_h - icon) / 2, icon, gap)

    elif layout_id == LAYOUT_WINDOWS11:
        # 下部のタスクバー（スタートとアイコンを中央に）
        bar_h = icon * 1.8
        fill(cr, color, 0.40, sx, sy + sh - bar_h, sw, bar_h, 2)
        count = 5
        row_w = count * icon + (count - 1) * gap
        draw_icons(cr, color, count, sx + (sw - row_w) / 2, sy + sh - bar_h + (bar_h - icon) / 2, icon, gap)

    elif layout_id == LAYOUT_MACOS:
        # 上部のメニューバー＋下部中央に浮いた Dock
        fill(cr, color, 0.30, sx, sy, sw, top_h, 2)
        count = 6
        row_w = count * icon + (count - 1) * gap
        dock_w = row_w + gap * 2
        dock_h = icon * 1.8
        dock_x = sx + (sw - dock_w) / 2
        dock_y = sy + sh - dock_h - gap
        fill(cr, color, 0.40, dock_x, dock_y, dock_w, dock_h, 4)
        draw_icons(cr, color, count, dock_x + gap, dock_y + (dock_h - icon) / 2, icon, gap)


def create_preview(layout_id):
    area = Gtk.DrawingArea(content_width=200, content_height=125, hexpand=True)
    area.set_draw_func(draw_layout_preview, layout_id)
    return area


# カードに並べるレイアウト（ID は detect_layout() の戻り値と同じ）
LAYOUTS = (
    (LAYOUT_ORIGINAL, "oYo Original"),
    (LAYOUT_WINDOWS10, "Windows 10"),
    (LAYOUT_WINDOWS11, "Windows 11"),
    (LAYOUT_MACOS, "macOS"),
)
LAYOUT_NAMES = dict(LAYOUTS)


class OyoUiChangerApp(Adw.Application):
    def __init__(self, state_reader=read_current_state):
        super().__init__(application_id="org.openyellowos.OyoUiChanger")
        self.state_reader = state_reader
        # current_layout: 今の GNOME の状態（判定結果）、selected_layout: カードで選んでいるもの
        self.current_layout = None
        self.selected_layout = None
        self.cards = {}
        self.current_badges = {}
        self.custom_notice = None
        self.window = None
        self.apply_button = None
        self.toast_overlay = None
        self.rollback_banner = None
        self.connect("activate", self.on_activate)
        self.connect("startup", self.on_startup)

    def on_startup(self, app):
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # 起動時に現在の設定を読み取り、今のレイアウトを判定する（read-only）
        # 管理対象の設定が手で変えられていれば custom（confirm_layout）
        state = self.state_reader()
        print_state(state)
        print(f"=== layout facts: {layout_facts(state)}")
        self.current_layout = confirm_layout(detect_layout(state))
        print(f"=== current layout: {self.current_layout}")

    def update_apply_button(self):
        # 今の状態と違うレイアウトを選んでいるときだけ Apply を押せるようにする
        changed = self.selected_layout is not None and self.selected_layout != self.current_layout
        self.apply_button.set_sensitive(changed)

    def on_layout_toggled(self, card, layout_id, check_icon):
        # 選択状態だけを記録する（設定の書き換えはまだ行わない）
        active = card.get_active()
        check_icon.set_opacity(1.0 if active else 0.0)
        if active:
            self.selected_layout = layout_id
            self.update_apply_button()

    def show_toast(self, message):
        print(message)
        self.toast_overlay.add_toast(Adw.Toast(title=message))

    def refresh_current_layout(self):
        """設定を読み直して current_layout と表示を更新する"""
        self.current_layout = confirm_layout(detect_layout(self.state_reader()))
        for layout_id, badge in self.current_badges.items():
            badge.set_visible(layout_id == self.current_layout)
        self.custom_notice.set_visible(self.current_layout == LAYOUT_CUSTOM)
        self.update_apply_button()

    def safe_refresh(self):
        """
        refresh_current_layout() を行い、成功したら True。失敗したらログに残してトーストで知らせ、False を返す
        （表示は前のまま。根拠なく custom にはしない）
        """
        try:
            self.refresh_current_layout()
        except Exception:
            print("Could not refresh the current layout:\n" + traceback.format_exc(), end="")
            self.show_toast(_(MSG_LAYOUT_CHECK_FAILED))
            return False
        return True

    def on_apply_clicked(self, button):
        layout_id = self.selected_layout
        name = LAYOUT_NAMES.get(layout_id, layout_id)
        if layout_id not in LAYOUT_PLANNERS:
            # 適用処理のないレイアウト（何も変更しない）
            self.show_toast(_("Not implemented yet."))
            return

        try:
            written = apply_layout(layout_id)
        except ApplyRollbackError as error:
            # 書き込みにも、元に戻すことにも失敗した: 一部が変わったままの可能性があるので、
            # 消えない警告を先に出してから状態を読み直す（読み直しに失敗しても警告は残す。詳細はログへ）
            print(f"Apply: {layout_id} failed: {error}; not restored: {error.failed}")
            self.rollback_banner.set_revealed(True)
            self.safe_refresh()
            return
        except ApplyWriteError as error:
            # 書き込み中の失敗: 元の値に戻してあるので、原因を知らせてから状態を読み直して表示を合わせる
            self.show_toast(str(error))
            self.safe_refresh()
            return
        except ApplyError as error:
            # 事前確認の失敗: 何も書いていないので、current_layout / selected_layout は変えない
            self.show_toast(str(error))
            return
        except Exception:
            # 想定外の例外（事前確認の途中など。書き込み中の例外は apply_plan が ApplyWriteError に包む）。
            # 中身は画面に出さずログに残す。Banner の状態は変えない
            print(f"Apply: {layout_id} failed with an unexpected error:\n{traceback.format_exc()}", end="")
            self.show_toast(_(MSG_UNEXPECTED_APPLY_ERROR))
            return

        print(f"Apply: {layout_id} wrote {written}")
        # Apply が成功したので、前回の「元に戻せなかった」警告は解除する
        self.rollback_banner.set_revealed(False)
        if not self.safe_refresh():
            # 書き込みは成功したが、適用されたかを確かめられない（読み直しの失敗はトーストで知らせた）
            return
        if self.current_layout == layout_id:
            self.show_toast(_("Applied {name}.").format(name=name))
        else:
            self.show_toast(_("Could not confirm that {name} was applied.").format(name=name))

    def create_card(self, layout_id, name):
        title = Gtk.Label(label=name, xalign=0, hexpand=True)
        title.add_css_class("heading")

        # 選択中だけ表示する（非表示でも場所は確保して、カードの大きさを変えない）
        check_icon = Gtk.Image(icon_name="object-select-symbolic", opacity=0.0)
        check_icon.add_css_class("layout-check")

        # 今 GNOME に適用されているレイアウトの印（選択中の印とは別。選択を変えても動かない）
        current_badge = Gtk.Label(label=_("Current"), valign=Gtk.Align.CENTER)
        current_badge.add_css_class("caption")
        current_badge.add_css_class("current-badge")
        current_badge.set_visible(layout_id == self.current_layout)
        self.current_badges[layout_id] = current_badge

        footer = Gtk.Box(spacing=6)
        footer.append(title)
        footer.append(current_badge)
        footer.append(check_icon)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.append(create_preview(layout_id))
        content.append(footer)

        # カード全体を1つのトグルボタンにして、どこをクリックしても選べるようにする
        card = Gtk.ToggleButton(child=content, tooltip_text=name)
        card.add_css_class("card")
        card.add_css_class("layout-card")
        card.update_property([Gtk.AccessibleProperty.LABEL], [name])
        card.connect("toggled", self.on_layout_toggled, layout_id, check_icon)
        return card

    def on_activate(self, app):
        # 2回目の起動では、すでにあるウィンドウを前面に出すだけにする
        if self.window is not None:
            self.window.present()
            return

        window = Adw.ApplicationWindow(application=app)
        window.set_title("oYo UI Changer")
        window.set_default_size(600, 600)
        self.window = window

        # 選択だけでは適用せず、Apply を押したときに適用する
        # （カードの初期選択より先に作り、最初から押せない状態にしておく）
        self.apply_button = Gtk.Button(label=_("Apply"), sensitive=False)
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self.on_apply_clicked)

        page = Adw.PreferencesPage()

        group = Adw.PreferencesGroup(
            title=_("Desktop Layout"),
            description=_("Choose a desktop layout style.")
        )

        # 今の状態がどのレイアウトにも一致しないときの案内（Custom 用のカードは作らない）
        self.custom_notice = Gtk.Box(spacing=8, margin_bottom=12)
        self.custom_notice.append(Gtk.Image(icon_name="dialog-information-symbolic"))
        notice_label = Gtk.Label(label=_("Current desktop layout is customized."), xalign=0, wrap=True)
        self.custom_notice.append(notice_label)
        self.custom_notice.add_css_class("dim-label")
        self.custom_notice.set_visible(self.current_layout == LAYOUT_CUSTOM)
        group.add(self.custom_notice)

        # 2×2 のカード。同じグループにまとめて、1つだけ選べるようにする
        grid = Gtk.Grid(row_spacing=18, column_spacing=18, column_homogeneous=True, row_homogeneous=True)
        first_card = None
        for index, (layout_id, name) in enumerate(LAYOUTS):
            card = self.create_card(layout_id, name)
            if first_card is None:
                first_card = card
            else:
                card.set_group(first_card)
            grid.attach(card, index % 2, index // 2, 1, 1)
            self.cards[layout_id] = card

        # 今のレイアウトのカードを選んだ状態にする（custom ならどれも選ばない）
        # selected_layout == current_layout になるので、Apply は押せないまま
        if self.current_layout in self.cards:
            self.cards[self.current_layout].set_active(True)

        group.add(grid)
        page.add(group)

        bottom_bar = Gtk.Box(halign=Gtk.Align.END)
        bottom_bar.set_margin_top(6)
        bottom_bar.set_margin_bottom(6)
        bottom_bar.set_margin_start(12)
        bottom_bar.set_margin_end(12)
        bottom_bar.append(self.apply_button)

        self.toast_overlay = Adw.ToastOverlay(child=page)

        # rollback が不完全だったときだけ出す、消えない警告（文はマークアップとして解釈しない）。
        # 閉じても GNOME の設定は変えない
        self.rollback_banner = Adw.Banner(title=_(MSG_ROLLBACK_INCOMPLETE), button_label=_("Dismiss"),
                                          use_markup=False, revealed=False)
        self.rollback_banner.connect("button-clicked", lambda banner: banner.set_revealed(False))

        toolbar_view = Adw.ToolbarView(content=self.toast_overlay)
        toolbar_view.add_top_bar(Adw.HeaderBar())
        toolbar_view.add_top_bar(self.rollback_banner)
        toolbar_view.add_bottom_bar(bottom_bar)

        window.set_content(toolbar_view)
        window.present()


app = OyoUiChangerApp()
app.run()
