"""
apply_layout() のテスト（memory backend 上で書き込み・rollback・設定の保持を確かめる）

旧スクラッチテストを移したもの。入力と期待値は変えていない。
旧テストの 1 チェックを 1 テストメソッドにしている（各テストで前提の設定から作り直す）。

uic-test9.py（oYo Original 適用）19 件
  T1: すでに Original → 書き込みなし                     2 件
  T2: Windows 相当 → Original（他 Extension の保持など）  9 件
  T3: disable-user-extensions = true → 書き込みなし      1 件
  T4: 適用処理のないレイアウト → 書き込みなし             1 件
  T5: 書き込み失敗 → rollback                            6 件
uic-test11.py（Windows 10 適用）32 件
  A : Original 相当 → Windows 10（空の辞書 → "0"）      16 件
  B : すでに Windows 10 → 書き込みなし                    1 件
  C : 複数モニター → 全モニターを Windows 10 にそろえる     6 件
  C2: panel-lengths がすべて 100 なら書かない              1 件
  D : disable-user-extensions = true → 書き込みなし        1 件
  E : 壊れた JSON → 書き込みなしで中止                    1 件
  F : 適用処理のないレイアウト → 書き込みなし              1 件
  G : 書き込み失敗 → rollback                             4 件
  H : 往復（Windows 10 → Original → Windows 10）          1 件
uic-test13.py（Windows 11 適用）29 件
  A : Original 相当 → Windows 11（空の辞書 → "0"）      13 件
  B : すでに Windows 11 → 書き込みなし                    1 件
  C : Windows 10 ⇔ Windows 11 の切り替え                  3 件
  D : 複数モニター                                        6 件
  E : disable-user-extensions = true → 書き込みなし        1 件
  F : 適用処理のないレイアウト → 書き込みなし              1 件
  G : 書き込み失敗（button-layout）→ rollback             3 件
  H : レイアウト ID と ArcMenu の値の分離                  1 件
uic-test15.py（ArcMenu の force-menu-location）16 件
  1: 対応表と値の範囲                                     3 件
  2: Original → Windows 11                                2 件
  3: Windows 11 → Windows 10                              2 件
  4: Windows 10 ⇔ Windows 11 の繰り返し                    1 件
  5: すでに目的の値なら書かない                            3 件
  6: ArcMenu のほかの設定に触れない                        2 件
  7: 書き込み失敗 → rollback に含まれる                    3 件
uic-test16.py（macOS 適用）53 件
  1: Original → macOS（他 Extension の保持、書く順番）     16 件
  2: すでに macOS → 書き込みなし                           1 件
  3: macOS → Original / Windows 10 / Windows 11            4 件
  4: Windows 10 / 11 → macOS                              16 件
  5: Original 経由と macOS 経由で Windows の状態が一致      2 件
  6: 往復（macOS → W10 → macOS → W11）                     1 件
  7: 複数モニター                                          9 件
  8: disable-user-extensions = true → 書き込みなし         1 件
  9: 書き込み失敗 → rollback                               3 件
実行: python3 -m unittest discover -s tests -v
"""

import json
import unittest

from helpers import load_app  # gi より先に読み込む（memory backend の強制）

from gi.repository import Gio  # noqa: E402  helpers のあとに読む

ns = load_app()

DOCK, PANEL, ARC = ns["DOCK_UUID"], ns["PANEL_UUID"], ns["ARCMENU_UUID"]
OTHERS = ["ding@rastersoft.com", "kimpanel@kde.org", "my-ext@example.com"]


def open_settings(schema_id, uuid=None):
    return ns["open_settings"](schema_id, uuid)[0]


def detect():
    return ns["detect_layout"](ns["read_current_state"]())


class ApplyTestCase(unittest.TestCase):
    """memory backend の設定を毎回まっさらにし、Gio.Settings 経由の書き込みを記録する"""

    def setUp(self):
        self.shell = open_settings(ns["SHELL_SCHEMA"])
        self.dock = open_settings(ns["DOCK_SCHEMA"], DOCK)
        self.panel = open_settings(ns["PANEL_SCHEMA"], PANEL)
        self.arc = open_settings(ns["ARCMENU_SCHEMA"], ARC)
        self.wm = open_settings(ns["WM_SCHEMA"])
        self.writes = []
        for meth in ("set_value", "reset"):
            orig = getattr(Gio.Settings, meth)

            def spy(settings, key, *args, _orig=orig, _meth=meth):
                self.writes.append((settings.props.schema_id, key, _meth))
                return _orig(settings, key, *args)
            setattr(Gio.Settings, meth, spy)
            self.addCleanup(setattr, Gio.Settings, meth, orig)

    def setup_state(self, enabled, disabled=(), disable_user=False, dock_pos="BOTTOM",
                    button="close,minimize,maximize:appmenu", dock_extra=None, panel_json=None, panel=None):
        """
        旧テストの setup() と同じ前提を作る（最後に書き込みの記録を空にする）。
        button=None なら button-layout は既定値のまま。panel は dash-to-panel の {キー: 文字列}
        """
        for settings in (self.shell, self.dock, self.wm, self.panel, self.arc):
            for key in settings.props.settings_schema.list_keys():
                settings.reset(key)
        self.shell.set_strv("enabled-extensions", list(enabled))
        self.shell.set_strv("disabled-extensions", list(disabled))
        self.shell.set_boolean("disable-user-extensions", disable_user)
        self.dock.set_string("dock-position", dock_pos)
        if button is not None:
            self.wm.set_string("button-layout", button)
        for key, value in (dock_extra or {}).items():
            self.dock.set_value(key, value)
        if panel_json:
            self.panel.set_string("panel-positions", panel_json)
        for key, value in (panel or {}).items():
            self.panel.set_string(key, value)
        Gio.Settings.sync()
        self.writes.clear()

    def all_settings(self):
        return (self.shell, self.dock, self.panel, self.arc, self.wm)

    def user_values(self):
        """5 つのスキーマの全キーのユーザー値（rollback の前後比較用）"""
        return {(s.props.schema_id, k): (s.get_user_value(k).unpack() if s.get_user_value(k) is not None else None)
                for s in self.all_settings() for k in s.props.settings_schema.list_keys()}

    def try_apply(self, layout_id):
        """旧テストの apply() と同じ。(書いたキー, None) か (None, 例外) を返す"""
        try:
            return ns["apply_layout"](layout_id), None
        except ns["ApplyError"] as error:
            return None, error

    def panel_json(self, key):
        return json.loads(self.panel.get_string(key))

    def assertPlainApplyError(self, error, message=None):
        """事前確認での失敗（ApplyWriteError ではない）"""
        self.assertIsInstance(error, ns["ApplyError"])
        self.assertNotIsInstance(error, ns["ApplyWriteError"])
        if message is not None:
            self.assertEqual(str(error), message)


class OriginalAlreadyAppliedTest(ApplyTestCase):
    """T1: すでに Original → 書き込みなし"""

    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], DOCK, OTHERS[1]], dock_pos="LEFT", button="appmenu:minimize,maximize,close",
                         dock_extra=ns["ORIGINAL_DOCK_SETTINGS"])
        self.before = detect()
        self.written = ns["apply_layout"]("original")

    def test_t1_1_precondition_original(self):
        self.assertEqual(self.before, "original")

    def test_t1_2_no_writes(self):
        self.assertEqual(self.written, [])
        self.assertEqual(self.writes, [])


class WindowsToOriginalTest(ApplyTestCase):
    """T2: Windows 相当 → Original"""

    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], PANEL, OTHERS[1], ARC, OTHERS[2]],
                         disabled=["foo@example.com", DOCK, "bar@example.com"], panel_json='{"0":"BOTTOM"}')
        self.before = detect()
        ns["apply_layout"]("original")

    def test_t2_1_precondition_windows10(self):
        self.assertEqual(self.before, "windows10")

    def test_t2_2_enabled_keeps_others_in_order(self):
        self.assertEqual(self.shell.get_strv("enabled-extensions"), OTHERS + [DOCK])

    def test_t2_3_disabled_keeps_others_in_order(self):
        self.assertEqual(self.shell.get_strv("disabled-extensions"), ["foo@example.com", "bar@example.com"])

    def test_t2_4_dock_targets(self):
        for key, value in ns["ORIGINAL_DOCK_SETTINGS"].items():
            self.assertTrue(self.dock.get_value(key).equal(value), key)

    def test_t2_5_button_layout(self):
        self.assertEqual(self.wm.get_string("button-layout"), "appmenu:minimize,maximize,close")

    def test_t2_6_disable_user_extensions_untouched(self):
        self.assertIs(self.shell.get_boolean("disable-user-extensions"), False)

    def test_t2_7_writes_within_allowed_set(self):
        allowed = ({(ns["DOCK_SCHEMA"], k) for k in ns["ORIGINAL_DOCK_SETTINGS"]}
                   | {(ns["WM_SCHEMA"], "button-layout"),
                      (ns["SHELL_SCHEMA"], "enabled-extensions"), (ns["SHELL_SCHEMA"], "disabled-extensions")})
        self.assertTrue(self.writes)
        for schema_id, key, meth in self.writes:
            self.assertIn((schema_id, key), allowed)
            self.assertEqual(meth, "set_value")

    def test_t2_8_detect_after_apply_original(self):
        self.assertEqual(detect(), "original")

    def test_t2_9_dash_to_panel_untouched(self):
        self.assertFalse([w for w in self.writes if w[0].endswith("dash-to-panel")])


class UserExtensionsDisabledTest(ApplyTestCase):
    """T3: disable-user-extensions = true → ApplyError、書き込みなし"""

    def test_t3_1_blocked_without_writes(self):
        self.setup_state([PANEL], disable_user=True)
        with self.assertRaises(ns["ApplyError"]) as caught:
            ns["apply_layout"]("original")
        self.assertNotIsInstance(caught.exception, ns["ApplyWriteError"])
        self.assertEqual(str(caught.exception), ns["MSG_USER_EXTENSIONS_DISABLED"])
        self.assertEqual(self.writes, [])


class NotImplementedLayoutTest(ApplyTestCase):
    """T4: 適用処理のないレイアウト（custom）→ ApplyError、書き込みなし"""

    def test_t4_1_custom_not_implemented(self):
        self.setup_state([DOCK])
        with self.assertRaises(ns["ApplyError"]) as caught:
            ns["apply_layout"]("custom")
        self.assertEqual(str(caught.exception), "Not implemented yet.")
        self.assertEqual(self.writes, [])


class RollbackTest(ApplyTestCase):
    """T5: Extension 一覧の書き込みを失敗させる → 書いた設定を元に戻す"""

    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], PANEL], dock_pos="RIGHT")
        self.dock.reset("dock-fixed")
        Gio.Settings.sync()
        self.writes.clear()
        self.before = {"enabled": self.shell.get_strv("enabled-extensions"),
                       "button": self.wm.get_string("button-layout")}

        orig = Gio.Settings.set_value

        def failing(settings, key, value):
            if key == "enabled-extensions":
                return False
            return orig(settings, key, value)
        Gio.Settings.set_value = failing
        try:
            ns["apply_layout"]("original")
            self.error = None
        except ns["ApplyWriteError"] as error:
            self.error = error
        finally:
            Gio.Settings.set_value = orig

    def test_t5_1_write_failure_raised(self):
        self.assertIsInstance(self.error, ns["ApplyWriteError"])

    def test_t5_2_dock_position_restored_to_user_value(self):
        user = self.dock.get_user_value("dock-position")
        self.assertIsNotNone(user)
        self.assertEqual(user.unpack(), "RIGHT")

    def test_t5_3_dock_fixed_back_to_no_user_value(self):
        self.assertIsNone(self.dock.get_user_value("dock-fixed"))

    def test_t5_4_button_layout_restored(self):
        self.assertEqual(self.wm.get_string("button-layout"), self.before["button"])

    def test_t5_5_enabled_unchanged(self):
        self.assertEqual(self.shell.get_strv("enabled-extensions"), self.before["enabled"])

    def test_t5_6_no_pending_changes(self):
        self.assertFalse(self.shell.get_has_unapplied())
        self.assertFalse(self.dock.get_has_unapplied())


#----------------------------------------------------------------------------------------------------------------
# Windows 10（旧 uic-test11.py）
#----------------------------------------------------------------------------------------------------------------
def compact_json(value):
    return json.dumps(value, separators=(",", ":"))


WINDOWS_ALLOWED = (
    {(ns["PANEL_SCHEMA"], k) for k in ("panel-positions", "panel-sizes", "panel-element-positions",
                                       "panel-lengths", "stockgs-keep-dash")}
    | {(ns["ARCMENU_SCHEMA"], k) for k in ("menu-layout", "position-in-panel", "dash-to-panel-standalone",
                                           "force-menu-location")}
    | {(ns["WM_SCHEMA"], "button-layout"),
       (ns["SHELL_SCHEMA"], "enabled-extensions"), (ns["SHELL_SCHEMA"], "disabled-extensions")}
)


class WindowsTestCase(ApplyTestCase):
    """旧 uic-test11.py / uic-test13.py / uic-test16.py の setup(): dock-position=LEFT、button-layout は既定値のまま"""

    def setup_state(self, enabled, disabled=(), disable_user=False, **panel):
        super().setup_state(enabled, disabled=disabled, disable_user=disable_user, dock_pos="LEFT",
                            button=None, panel=panel)

    def setup_from_original(self):
        """A の前提: Original 相当（dash-to-panel / ArcMenu は disabled、standalone=true）"""
        self.setup_state([OTHERS[0], DOCK, OTHERS[1], OTHERS[2]],
                         disabled=["foo@example.com", ARC, PANEL, "bar@example.com"])
        self.arc.set_boolean("dash-to-panel-standalone", True)
        Gio.Settings.sync()
        self.writes.clear()


class Windows10FromOriginalTest(WindowsTestCase):
    """A: Original 相当 → Windows 10（空の辞書 → "0"）"""

    def setUp(self):
        super().setUp()
        self.setup_from_original()
        self.before = detect()
        self.written, self.error = self.try_apply("windows10")

    def test_a01_precondition_original(self):
        self.assertEqual(self.before, "original")

    def test_a02_applied_without_error(self):
        self.assertIsNone(self.error)

    def test_a03_enabled(self):
        self.assertEqual(self.shell.get_strv("enabled-extensions"), OTHERS + [PANEL, ARC])

    def test_a04_disabled(self):
        self.assertEqual(self.shell.get_strv("disabled-extensions"), ["foo@example.com", "bar@example.com"])

    def test_a05_panel_positions(self):
        self.assertEqual(self.panel_json("panel-positions"), {"0": "BOTTOM"})

    def test_a06_panel_sizes(self):
        self.assertEqual(self.panel_json("panel-sizes"), {"0": 36})

    def test_a07_elements_windows10(self):
        elements = self.panel_json("panel-element-positions")
        self.assertEqual(list(elements), ["0"])
        self.assertEqual(elements["0"], ns["WINDOWS10_ELEMENTS"])
        taskbar = [e for e in elements["0"] if e["element"] == "taskbar"][0]
        self.assertEqual(taskbar, {"element": "taskbar", "visible": True, "position": "stackedTL"})

    def test_a08_panel_lengths_untouched(self):
        self.assertEqual(self.panel.get_string("panel-lengths"), "{}")

    def test_a09_arcmenu(self):
        self.assertEqual(self.arc.get_string("menu-layout"), "windows")
        self.assertIs(self.arc.get_boolean("dash-to-panel-standalone"), False)
        self.assertEqual(self.arc.get_string("position-in-panel"), "Left")

    def test_a10_position_in_panel_not_written(self):
        self.assertNotIn((ns["ARCMENU_SCHEMA"], "position-in-panel", "set_value"), self.writes)

    def test_a11_button_layout(self):
        self.assertEqual(self.wm.get_string("button-layout"), "appmenu:minimize,maximize,close")

    def test_a12_dock_settings_untouched(self):
        self.assertFalse([w for w in self.writes if w[0] == ns["DOCK_SCHEMA"]])
        self.assertEqual(self.dock.get_string("dock-position"), "LEFT")

    def test_a13_stockgs_keep_dash_and_panel_anchors_untouched(self):
        self.assertFalse([w for w in self.writes if w[1] in ("stockgs-keep-dash", "panel-anchors")])

    def test_a14_writes_within_allowed(self):
        self.assertTrue(self.writes)
        for schema_id, key, meth in self.writes:
            self.assertIn((schema_id, key), WINDOWS_ALLOWED)
            self.assertEqual(meth, "set_value")

    def test_a15_disable_user_extensions_untouched(self):
        self.assertIs(self.shell.get_boolean("disable-user-extensions"), False)

    def test_a16_detect_windows10(self):
        self.assertEqual(detect(), "windows10")


class Windows10AlreadyAppliedTest(WindowsTestCase):
    """B: A のあと、もう一度 Windows 10 → 書き込みなし"""

    def test_b1_second_apply_no_writes(self):
        self.setup_from_original()
        self.try_apply("windows10")
        self.writes.clear()
        written, error = self.try_apply("windows10")
        self.assertIsNone(error)
        self.assertEqual(written, [])
        self.assertEqual(self.writes, [])


class Windows10MultiMonitorTest(WindowsTestCase):
    """C: 複数モニター・既存の鍵 → 全部の鍵を Windows 10 にそろえる、lengths は 100 に"""

    def setUp(self):
        super().setUp()
        self.setup_state(
            [DOCK, OTHERS[1]],
            **{"panel-positions": compact_json({"AAA-1": "TOP", "BBB-2": "LEFT"}),
               "panel-sizes": compact_json({"AAA-1": 48, "BBB-2": 20}),
               "panel-element-positions": compact_json(
                   {"AAA-1": [{"element": "taskbar", "visible": False, "position": "centered"}], "BBB-2": []}),
               "panel-lengths": compact_json({"AAA-1": -1, "BBB-2": 100})})
        self.try_apply("windows10")

    def test_c1_positions(self):
        self.assertEqual(self.panel_json("panel-positions"), {"AAA-1": "BOTTOM", "BBB-2": "BOTTOM"})

    def test_c2_sizes(self):
        self.assertEqual(self.panel_json("panel-sizes"), {"AAA-1": 36, "BBB-2": 36})

    def test_c3_elements_all_windows10(self):
        elements = self.panel_json("panel-element-positions")
        self.assertEqual(list(elements), ["AAA-1", "BBB-2"])
        for value in elements.values():
            self.assertEqual(value, ns["WINDOWS10_ELEMENTS"])

    def test_c4_lengths(self):
        self.assertEqual(self.panel_json("panel-lengths"), {"AAA-1": 100, "BBB-2": 100})

    def test_c5_no_fallback_key_added(self):
        for key in ("panel-positions", "panel-sizes", "panel-element-positions", "panel-lengths"):
            self.assertNotIn("0", self.panel_json(key), key)

    def test_c6_detect_windows10(self):
        self.assertEqual(detect(), "windows10")


class Windows10LengthsAlready100Test(WindowsTestCase):
    """C2: panel-lengths がすべて 100 なら書かない"""

    def test_cc1_lengths_not_written(self):  # 旧 C2（C の test_c2_sizes と区別するため cc）
        self.setup_state([DOCK], **{"panel-lengths": compact_json({"X": 100})})
        self.try_apply("windows10")
        self.assertNotIn((ns["PANEL_SCHEMA"], "panel-lengths", "set_value"), self.writes)


class Windows10UserExtensionsDisabledTest(WindowsTestCase):
    """D: disable-user-extensions = true → 書き込みなし"""

    def test_d1_blocked_without_writes(self):
        self.setup_state([DOCK], disable_user=True)
        _written, error = self.try_apply("windows10")
        self.assertPlainApplyError(error, ns["MSG_USER_EXTENSIONS_DISABLED"])
        self.assertEqual(self.writes, [])


class Windows10BrokenJsonTest(WindowsTestCase):
    """E: 壊れた JSON → 書き込みなしで中止"""

    def test_e1_broken_json_aborts_without_writes(self):
        self.setup_state([DOCK], **{"panel-sizes": "{broken"})
        _written, error = self.try_apply("windows10")
        self.assertPlainApplyError(error)
        self.assertIn("panel-sizes", str(error))
        self.assertEqual(self.writes, [])


class Windows10NotImplementedLayoutTest(WindowsTestCase):
    """F: 適用処理のないレイアウト（custom）→ 書き込みなし"""

    def test_f1_custom_not_implemented(self):
        self.setup_state([DOCK])
        _written, error = self.try_apply("custom")
        self.assertPlainApplyError(error, "Not implemented yet.")
        self.assertEqual(self.writes, [])


class Windows10RollbackTest(WindowsTestCase):
    """G: Extension 一覧の書き込みを失敗させる → 全キーのユーザー値が元どおり"""

    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], DOCK], **{"panel-positions": compact_json({"AAA-1": "TOP"})})
        self.arc.set_string("menu-layout", "brisk")
        Gio.Settings.sync()
        self.writes.clear()
        self.before = self.user_values()

        orig = Gio.Settings.set_value

        def failing(settings, key, value):
            if key == "enabled-extensions":
                return False
            return orig(settings, key, value)
        Gio.Settings.set_value = failing
        try:
            self.written, self.error = self.try_apply("windows10")
        finally:
            Gio.Settings.set_value = orig

    def test_g1_write_failure_raised(self):
        self.assertIsInstance(self.error, ns["ApplyWriteError"])

    def test_g2_all_user_values_restored_exactly(self):
        after = self.user_values()
        diff = {k: (v, after[k]) for k, v in self.before.items() if v != after[k]}
        self.assertEqual(diff, {})

    def test_g3_no_pending_changes(self):
        for settings in self.all_settings():
            self.assertFalse(settings.get_has_unapplied(), settings.props.schema_id)

    def test_g4_detect_still_original(self):
        self.assertEqual(detect(), "original")


class Windows10RoundTripTest(WindowsTestCase):
    """H: 往復（Windows 10 → Original → Windows 10）"""

    def test_h1_round_trip(self):
        self.setup_state([OTHERS[0], DOCK])
        seq = []
        for layout_id in ("windows10", "original", "windows10"):
            self.try_apply(layout_id)
            seq.append(detect())
        self.assertEqual(seq, ["windows10", "original", "windows10"])


#----------------------------------------------------------------------------------------------------------------
# Windows 11（旧 uic-test13.py）
#----------------------------------------------------------------------------------------------------------------
class Windows11StateChecks:
    """旧 w11_checks() の 5 件。A と D で使う（self.keys: 期待するモニターの鍵）"""

    keys = ("0",)

    def test_w11_1_elements_all_windows11(self):
        elements = self.panel_json("panel-element-positions")
        self.assertEqual(list(elements), list(self.keys))
        for value in elements.values():
            self.assertEqual(value, ns["WINDOWS11_ELEMENTS"])

    def test_w11_2_centerbox_directly_before_taskbar(self):
        elements = self.panel_json("panel-element-positions")[self.keys[0]]
        names = [e["element"] for e in elements]
        center_box = next(e for e in elements if e["element"] == "centerBox")
        taskbar = next(e for e in elements if e["element"] == "taskbar")
        self.assertEqual(names.index("taskbar"), names.index("centerBox") + 1)
        self.assertEqual(center_box["position"], "centerMonitor")
        self.assertEqual(taskbar["position"], "centerMonitor")
        self.assertTrue(center_box["visible"])
        self.assertTrue(taskbar["visible"])

    def test_w11_3_arcmenu(self):
        self.assertEqual((self.arc.get_string("menu-layout"), self.arc.get_string("position-in-panel"),
                          self.arc.get_boolean("dash-to-panel-standalone")), ("11", "Center", False))

    def test_w11_4_positions_and_sizes(self):
        self.assertEqual(self.panel_json("panel-positions"), {k: "BOTTOM" for k in self.keys})
        self.assertEqual(self.panel_json("panel-sizes"), {k: 36 for k in self.keys})

    def test_w11_5_detect_windows11(self):
        self.assertEqual(detect(), "windows11")


class Windows11FromOriginalTest(Windows11StateChecks, WindowsTestCase):
    """A: Original 相当 → Windows 11（空の辞書 → "0"）。w11 の 5 件 ＋ 8 件"""

    def setUp(self):
        super().setUp()
        self.setup_from_original()
        self.before = detect()
        self.written, self.error = self.try_apply("windows11")

    def test_a01_precondition_original(self):
        self.assertEqual(self.before, "original")

    def test_a02_applied_without_error(self):
        self.assertIsNone(self.error)

    def test_a08_enabled(self):
        self.assertEqual(self.shell.get_strv("enabled-extensions"), OTHERS + [PANEL, ARC])

    def test_a09_disabled(self):
        self.assertEqual(self.shell.get_strv("disabled-extensions"), ["foo@example.com", "bar@example.com"])

    def test_a10_panel_lengths_untouched(self):
        self.assertEqual(self.panel.get_string("panel-lengths"), "{}")

    def test_a11_button_layout(self):
        self.assertEqual(self.wm.get_string("button-layout"), "appmenu:minimize,maximize,close")

    def test_a12_writes_within_allowed(self):
        self.assertTrue(self.writes)
        for schema_id, key, meth in self.writes:
            self.assertIn((schema_id, key), WINDOWS_ALLOWED)
            self.assertEqual(meth, "set_value")

    def test_a13_dock_settings_untouched(self):
        self.assertFalse([w for w in self.writes if w[0] == ns["DOCK_SCHEMA"]])


class Windows11AlreadyAppliedTest(WindowsTestCase):
    """B: A のあと、もう一度 Windows 11 → 書き込みなし"""

    def test_b1_second_apply_no_writes(self):
        self.setup_from_original()
        self.try_apply("windows11")
        self.writes.clear()
        written, error = self.try_apply("windows11")
        self.assertIsNone(error)
        self.assertEqual(written, [])
        self.assertEqual(self.writes, [])


class Windows11SwitchTest(WindowsTestCase):
    """C: Windows 10 → Windows 11 → Windows 10 → Windows 11 → Original"""

    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], DOCK])
        self.try_apply("windows10")
        self.seq = [detect()]
        self.first_position = self.arc.get_string("position-in-panel")
        self.writes.clear()
        self.try_apply("windows11")
        self.switch_writes = {(s.split(".")[-1], k) for s, k, _m in self.writes}
        self.seq.append(detect())
        self.try_apply("windows10")
        self.seq.append(detect())
        self.back_position = self.arc.get_string("position-in-panel")
        self.back_layout = self.arc.get_string("menu-layout")
        for layout_id in ("windows11", "original"):
            self.try_apply(layout_id)
            self.seq.append(detect())

    def test_c1_windows10_to_windows11_writes_only(self):
        self.assertEqual(self.switch_writes, {("dash-to-panel", "panel-element-positions"),
                                              ("arcmenu", "menu-layout"), ("arcmenu", "position-in-panel"),
                                              ("arcmenu", "force-menu-location")})

    def test_c2_sequence(self):
        self.assertEqual(self.seq, ["windows10", "windows11", "windows10", "windows11", "original"])

    def test_c3_back_to_windows10_restores_arcmenu(self):
        self.assertEqual((self.first_position, self.back_position, self.back_layout), ("Left", "Left", "windows"))


class Windows11MultiMonitorTest(Windows11StateChecks, WindowsTestCase):
    """D: 複数モニター。w11 の 5 件 ＋ lengths 1 件"""

    keys = ("AAA-1", "BBB-2")

    def setUp(self):
        super().setUp()
        self.setup_state(
            [DOCK],
            **{"panel-positions": compact_json({"AAA-1": "TOP", "BBB-2": "LEFT"}),
               "panel-sizes": compact_json({"AAA-1": 48, "BBB-2": 20}),
               "panel-element-positions": compact_json({"AAA-1": ns["WINDOWS10_ELEMENTS"], "BBB-2": []}),
               "panel-lengths": compact_json({"AAA-1": -1, "BBB-2": 60})})
        self.try_apply("windows11")

    def test_d6_lengths(self):
        self.assertEqual(self.panel_json("panel-lengths"), {"AAA-1": 100, "BBB-2": 100})


class Windows11UserExtensionsDisabledTest(WindowsTestCase):
    """E: disable-user-extensions = true → 書き込みなし"""

    def test_e1_blocked_without_writes(self):
        self.setup_state([DOCK], disable_user=True)
        _written, error = self.try_apply("windows11")
        self.assertPlainApplyError(error, ns["MSG_USER_EXTENSIONS_DISABLED"])
        self.assertEqual(self.writes, [])


class Windows11NotImplementedLayoutTest(WindowsTestCase):
    """F: 適用処理のないレイアウト（custom）→ 書き込みなし"""

    def test_f1_custom_not_implemented(self):
        self.setup_state([DOCK])
        _written, error = self.try_apply("custom")
        self.assertPlainApplyError(error, "Not implemented yet.")
        self.assertEqual(self.writes, [])


class Windows11RollbackTest(WindowsTestCase):
    """G: button-layout の書き込みを失敗させる（パネル・ArcMenu は書いたあと）→ 元どおり"""

    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], PANEL, ARC],
                         **{"panel-positions": compact_json({"AAA-1": "BOTTOM"}),
                            "panel-element-positions": compact_json({"AAA-1": ns["WINDOWS10_ELEMENTS"]})})
        self.arc.set_string("menu-layout", "windows")
        self.arc.set_string("position-in-panel", "Left")
        Gio.Settings.sync()
        self.writes.clear()
        self.before = self.user_values()
        self.before_layout = detect()

        orig = Gio.Settings.set_value

        def failing(settings, key, value):
            if key == "button-layout":
                return False
            return orig(settings, key, value)
        Gio.Settings.set_value = failing
        try:
            self.written, self.error = self.try_apply("windows11")
        finally:
            Gio.Settings.set_value = orig

    def test_g1_write_failure_raised(self):
        self.assertIsInstance(self.error, ns["ApplyWriteError"])

    def test_g2_restored_exactly(self):
        after = self.user_values()
        diff = {k: (v, after[k]) for k, v in self.before.items() if v != after[k]}
        self.assertEqual(diff, {})

    def test_g3_no_pending_and_detect_unchanged(self):
        for settings in self.all_settings():
            self.assertFalse(settings.get_has_unapplied(), settings.props.schema_id)
        self.assertEqual(self.before_layout, "windows10")
        self.assertEqual(detect(), "windows10")


class LayoutIdTest(unittest.TestCase):
    """H: UI Changer のレイアウト ID に ArcMenu の値（'11' など）を使っていない"""

    def test_h1_layout_ids_separated_from_arcmenu_values(self):
        self.assertEqual([i for i, _name in ns["LAYOUTS"]], ["original", "windows10", "windows11", "macos"])
        self.assertNotIn("11", ns["LAYOUT_NAMES"])
        self.assertEqual(ns["ARCMENU_LAYOUT"], {"windows10": "windows", "windows11": "11", "macos": "brisk"})


#----------------------------------------------------------------------------------------------------------------
# ArcMenu の force-menu-location（旧 uic-test15.py）
#----------------------------------------------------------------------------------------------------------------
ARCMENU_MANAGED_KEYS = {"menu-layout", "position-in-panel", "dash-to-panel-standalone", "force-menu-location"}
FORCE_MENU_LOCATION_WRITE = (ns["ARCMENU_SCHEMA"], "force-menu-location", "set_value")


class ArcMenuTestCase(ApplyTestCase):
    """旧 uic-test15.py の setup(): 全キーを戻し、enabled-extensions と dock-position=LEFT だけを設定する"""

    def setup_state(self, enabled):
        for settings in self.all_settings():
            for key in settings.props.settings_schema.list_keys():
                settings.reset(key)
        self.shell.set_strv("enabled-extensions", list(enabled))
        self.dock.set_string("dock-position", "LEFT")
        Gio.Settings.sync()
        self.writes.clear()

    def location(self):
        return self.arc.get_string("force-menu-location")


class ArcMenuMappingTest(ArcMenuTestCase):
    """1: 対応表と事前確認（range）"""

    def test_1_1_mapping(self):
        self.assertEqual(ns["ARCMENU_MENU_LOCATION"],
                         {"windows10": "Off", "windows11": "BottomCentered", "macos": "Off"})

    def assert_in_range(self, layout_id):
        key = self.arc.props.settings_schema.get_key("force-menu-location")
        self.assertTrue(key.range_check(ns["arcmenu_settings"](layout_id)["force-menu-location"]))

    def test_1_2_windows10_value_in_range(self):
        self.assert_in_range("windows10")

    def test_1_3_windows11_value_in_range(self):
        self.assert_in_range("windows11")


class ArcMenuOriginalToWindows11Test(ArcMenuTestCase):
    """2: Original → Windows 11（既定 Off → BottomCentered）"""

    def setUp(self):
        super().setUp()
        self.setup_state([DOCK])
        self.try_apply("windows11")

    def test_2_1_bottom_centered(self):
        self.assertEqual(self.location(), "BottomCentered")
        self.assertEqual(detect(), "windows11")

    def test_2_2_written_once(self):
        self.assertEqual(self.writes.count(FORCE_MENU_LOCATION_WRITE), 1)


class ArcMenuWindows11ToWindows10Test(ArcMenuTestCase):
    """3: 2 のあと Windows 11 → Windows 10（BottomCentered → Off）"""

    def setUp(self):
        super().setUp()
        self.setup_state([DOCK])
        self.try_apply("windows11")
        self.writes.clear()
        self.try_apply("windows10")

    def test_3_1_off(self):
        self.assertEqual(self.location(), "Off")
        self.assertEqual(detect(), "windows10")

    def test_3_2_written_on_switch(self):
        self.assertIn(FORCE_MENU_LOCATION_WRITE, self.writes)


class ArcMenuToggleTest(ArcMenuTestCase):
    """4: 3 のあと Windows 11 → Windows 10 → Windows 11 → Windows 10"""

    def test_4_1_toggle_sequence(self):
        self.setup_state([DOCK])
        self.try_apply("windows11")
        self.try_apply("windows10")
        seq = []
        for layout_id in ("windows11", "windows10", "windows11", "windows10"):
            self.try_apply(layout_id)
            seq.append((layout_id, self.location()))
        self.assertEqual(seq, [("windows11", "BottomCentered"), ("windows10", "Off"),
                               ("windows11", "BottomCentered"), ("windows10", "Off")])


class ArcMenuNoRewriteTest(ArcMenuTestCase):
    """5: すでに目的の値なら書かない"""

    def test_5_1_windows10_again_no_writes(self):
        self.setup_state([DOCK])
        self.try_apply("windows10")
        self.writes.clear()
        self.try_apply("windows10")
        self.assertEqual(self.writes, [])

    def test_5_2_windows11_again_no_writes(self):
        # 旧テストでは 5_1 の続き（Windows 10 → Windows 11 → もう一度 Windows 11）
        self.setup_state([DOCK])
        self.try_apply("windows10")
        self.try_apply("windows10")
        self.try_apply("windows11")
        self.writes.clear()
        self.try_apply("windows11")
        self.assertEqual(self.writes, [])

    def test_5_3_original_to_windows10_not_written(self):
        # Windows 10 の値は既定値と同じ Off なので、Original から切り替えても書かない
        self.setup_state([DOCK])
        self.try_apply("windows10")
        self.assertNotIn(FORCE_MENU_LOCATION_WRITE, self.writes)
        self.assertEqual(self.location(), "Off")


class ArcMenuOtherSettingsTest(ArcMenuTestCase):
    """6: ArcMenu のほかの設定に触れない"""

    def setUp(self):
        super().setUp()
        self.setup_state([DOCK])
        self.arc.set_int("menu-height", 640)
        self.arc.set_boolean("eleven-show-frequent-apps", False)
        self.arc.set_string("menu-button-icon", "oyo-logo")
        Gio.Settings.sync()
        self.writes.clear()
        for layout_id in ("windows11", "windows10", "windows11"):
            self.try_apply(layout_id)

    def test_6_1_only_managed_keys_written(self):
        written = {k for s, k, _m in self.writes if s == ns["ARCMENU_SCHEMA"]}
        self.assertLessEqual(written, ARCMENU_MANAGED_KEYS)

    def test_6_2_other_settings_preserved(self):
        self.assertEqual(self.arc.get_int("menu-height"), 640)
        self.assertIs(self.arc.get_boolean("eleven-show-frequent-apps"), False)
        self.assertEqual(self.arc.get_string("menu-button-icon"), "oyo-logo")


class ArcMenuRollbackTest(ArcMenuTestCase):
    """7: Windows 10 → 11 の途中で失敗 → force-menu-location も元に戻る"""

    def setUp(self):
        super().setUp()
        self.setup_state([DOCK])
        self.try_apply("windows10")
        Gio.Settings.sync()
        user = self.arc.get_user_value("force-menu-location")
        self.before_user = None if user is None else user.unpack()

        orig = Gio.Settings.set_value

        def failing(settings, key, value):
            if key in ("button-layout", "enabled-extensions"):
                return False
            return orig(settings, key, value)
        Gio.Settings.set_value = failing
        try:
            # button-layout を目標と違う値にして、書き込み失敗を起こす（set_string は失敗させる対象外）
            self.wm.set_string("button-layout", "close:")
            Gio.Settings.sync()
            self.writes.clear()
            self.written, self.error = self.try_apply("windows11")
        finally:
            Gio.Settings.set_value = orig

    def test_7_1_failure_raised(self):
        self.assertIsInstance(self.error, ns["ApplyWriteError"])

    def test_7_2_written_then_rolled_back(self):
        self.assertIn(FORCE_MENU_LOCATION_WRITE, self.writes)
        user = self.arc.get_user_value("force-menu-location")
        self.assertEqual(None if user is None else user.unpack(), self.before_user)
        self.assertEqual(self.location(), "Off")

    def test_7_3_detect_still_windows10(self):
        self.assertEqual(detect(), "windows10")


#----------------------------------------------------------------------------------------------------------------
# macOS（旧 uic-test16.py）
#----------------------------------------------------------------------------------------------------------------
def short_schema(schema_id):
    """旧テストの記録と同じ、スキーマ ID の最後の部分（dash-to-dock、preferences など）"""
    return schema_id.split(".")[-1]


MACOS_ALLOWED = (
    {("dash-to-dock", k) for k in ns["MACOS_DOCK_SETTINGS"]}
    | {("dash-to-panel", k) for k in ("panel-positions", "panel-sizes", "panel-element-positions",
                                      "panel-lengths", "stockgs-keep-dash")}
    | {("arcmenu", k) for k in ("menu-layout", "position-in-panel", "dash-to-panel-standalone",
                                "force-menu-location")}
    | {("preferences", "button-layout"), ("shell", "enabled-extensions"), ("shell", "disabled-extensions")}
)


class MacStateChecks:
    """旧 mac_state() の 8 件。1 / 4 / 7 で使う（self.keys: 期待するモニターの鍵）"""

    keys = ("0",)

    def test_mac_1_detect_macos(self):
        self.assertEqual(detect(), "macos")

    def test_mac_2_elements_all_macos(self):
        elements = self.panel_json("panel-element-positions")
        self.assertEqual(list(elements), list(self.keys))
        for value in elements.values():
            self.assertEqual(value, ns["MACOS_ELEMENTS"])

    def test_mac_3_taskbar_and_desktop_button_hidden(self):
        by_name = {e["element"]: e for e in self.panel_json("panel-element-positions")[self.keys[0]]}
        self.assertIs(by_name["taskbar"]["visible"], False)
        self.assertIs(by_name["desktopButton"]["visible"], False)
        self.assertIs(by_name["leftBox"]["visible"], True)

    def test_mac_4_positions_top_sizes_32(self):
        self.assertEqual(self.panel_json("panel-positions"), {k: "TOP" for k in self.keys})
        self.assertEqual(self.panel_json("panel-sizes"), {k: 32 for k in self.keys})

    def test_mac_5_stockgs_keep_dash(self):
        self.assertIs(self.panel.get_boolean("stockgs-keep-dash"), True)

    def test_mac_6_dock(self):
        self.assertEqual({k: self.dock.get_value(k).unpack() for k in ns["MACOS_DOCK_SETTINGS"]},
                         {"dock-position": "BOTTOM", "extend-height": False, "dash-max-icon-size": 38,
                          "show-apps-at-top": True, "dock-fixed": True, "custom-theme-shrink": True,
                          "running-indicator-style": "DOTS", "transparency-mode": "DYNAMIC",
                          "click-action": "minimize"})

    def test_mac_7_arcmenu(self):
        self.assertEqual((self.arc.get_string("menu-layout"), self.arc.get_string("position-in-panel"),
                          self.arc.get_string("force-menu-location"), self.arc.get_boolean("dash-to-panel-standalone")),
                         ("brisk", "Left", "Off", False))

    def test_mac_8_button_layout(self):
        self.assertEqual(self.wm.get_string("button-layout"), "close,minimize,maximize:appmenu")


class MacosTestCase(WindowsTestCase):
    def setup_from_original(self):
        """1 の前提: Original 相当（dash-to-panel / ArcMenu は disabled）"""
        self.setup_state([OTHERS[0], DOCK, OTHERS[1], OTHERS[2]],
                         disabled=["foo@example.com", PANEL, ARC, "bar@example.com"])


class MacosFromOriginalTest(MacStateChecks, MacosTestCase):
    """1: Original → macOS。mac_state の 8 件 ＋ 8 件"""

    def setUp(self):
        super().setUp()
        self.setup_from_original()
        self.before = detect()
        self.written, self.error = self.try_apply("macos")

    def test_1_01_precondition_original(self):
        self.assertEqual(self.before, "original")

    def test_1_02_applied_without_error(self):
        self.assertIsNone(self.error)

    def test_1_11_enabled(self):
        self.assertEqual(self.shell.get_strv("enabled-extensions"),
                         [OTHERS[0], DOCK, OTHERS[1], OTHERS[2], PANEL, ARC])

    def test_1_12_disabled(self):
        self.assertEqual(self.shell.get_strv("disabled-extensions"), ["foo@example.com", "bar@example.com"])

    def test_1_13_writes_within_allowed(self):
        self.assertTrue(self.writes)
        for schema_id, key, meth in self.writes:
            self.assertIn((short_schema(schema_id), key), MACOS_ALLOWED)
            self.assertEqual(meth, "set_value")

    def test_1_14_panel_lengths_untouched(self):
        self.assertEqual(self.panel.get_string("panel-lengths"), "{}")

    def test_1_15_disable_user_extensions_untouched(self):
        self.assertIs(self.shell.get_boolean("disable-user-extensions"), False)

    def test_1_16_write_order(self):
        # Dock → パネル → ArcMenu → ボタンの配置 → Extension の一覧
        order = []
        for schema_id, _key, _meth in self.writes:
            if not order or order[-1] != short_schema(schema_id):
                order.append(short_schema(schema_id))
        self.assertEqual(order, ["dash-to-dock", "dash-to-panel", "arcmenu", "preferences", "shell"])


class MacosSwitchTest(MacosTestCase):
    """2: すでに macOS → 書き込みなし ／ 3: macOS → Original / Windows 10 / Windows 11"""

    def test_2_1_already_macos_no_writes(self):
        self.setup_from_original()
        self.try_apply("macos")
        self.writes.clear()
        written, error = self.try_apply("macos")
        self.assertIsNone(error)
        self.assertEqual(written, [])
        self.assertEqual(self.writes, [])

    def test_3_1_macos_to_original(self):
        # 旧テストでは 1 → 2 の続き
        self.setup_from_original()
        self.try_apply("macos")
        self.try_apply("macos")
        self.try_apply("original")
        self.assertEqual(detect(), "original")

    def macos_to_windows10(self):
        self.setup_state([DOCK])
        self.try_apply("macos")
        self.try_apply("windows10")

    def test_3_2_macos_to_windows10(self):
        self.macos_to_windows10()
        self.assertEqual(detect(), "windows10")
        self.assertIs(self.panel.get_boolean("stockgs-keep-dash"), False)

    def test_3_3_dock_disabled(self):
        # Dock は無効になるだけで、Dock の設定は macOS のまま残る（旧テストどおり、ここでは確認しない）
        self.macos_to_windows10()
        self.assertNotIn(DOCK, self.shell.get_strv("enabled-extensions"))

    def test_3_4_macos_to_windows11(self):
        # 旧テストでは 3_2 の続き（→ macOS → Windows 11）
        self.macos_to_windows10()
        self.try_apply("macos")
        self.try_apply("windows11")
        self.assertEqual(detect(), "windows11")
        self.assertIs(self.panel.get_boolean("stockgs-keep-dash"), False)
        self.assertEqual(self.arc.get_string("force-menu-location"), "BottomCentered")


class MacosFromWindows10Test(MacStateChecks, MacosTestCase):
    """4: Windows 10 → macOS（mac_state の 8 件）"""

    def setUp(self):
        super().setUp()
        self.setup_state([DOCK])
        self.try_apply("windows10")
        self.try_apply("macos")


class MacosFromWindows11Test(MacStateChecks, MacosTestCase):
    """4: Windows 11 → macOS（mac_state の 8 件）"""

    def setUp(self):
        super().setUp()
        self.setup_state([DOCK])
        self.try_apply("windows11")
        self.try_apply("macos")


class MacosPathIndependenceTest(MacosTestCase):
    """5: Original → Windows と macOS → Windows の最終状態が一致する（管理対象キー）／ 6: 往復"""

    def snapshot(self):
        state = {k: self.panel.get_value(k).unpack()
                 for k in ("panel-positions", "panel-sizes", "panel-element-positions", "panel-lengths",
                           "stockgs-keep-dash")}
        state.update({k: self.arc.get_value(k).unpack()
                      for k in ("menu-layout", "position-in-panel", "force-menu-location", "dash-to-panel-standalone")})
        state.update({"button-layout": self.wm.get_string("button-layout"),
                      "enabled": self.shell.get_strv("enabled-extensions")})
        return state

    def assert_same_via_macos(self, target):
        self.setup_state([OTHERS[0], DOCK])
        self.try_apply(target)
        direct = self.snapshot()
        self.setup_state([OTHERS[0], DOCK])
        self.try_apply("macos")
        self.try_apply(target)
        via_macos = self.snapshot()
        self.assertEqual({k: (v, via_macos[k]) for k, v in direct.items() if v != via_macos[k]}, {})

    def test_5_1_windows10_same_via_macos(self):
        self.assert_same_via_macos("windows10")

    def test_5_2_windows11_same_via_macos(self):
        self.assert_same_via_macos("windows11")

    def test_6_1_round_trip(self):
        self.setup_state([DOCK])
        seq = []
        for layout_id in ("macos", "windows10", "macos", "windows11"):
            self.try_apply(layout_id)
            seq.append(detect())
        self.assertEqual(seq, ["macos", "windows10", "macos", "windows11"])


class MacosMultiMonitorTest(MacStateChecks, MacosTestCase):
    """7: 複数モニター（mac_state の 8 件 ＋ lengths 1 件）"""

    keys = ("A-1", "B-2")

    def setUp(self):
        super().setUp()
        self.setup_state(
            [DOCK],
            **{"panel-positions": compact_json({"A-1": "BOTTOM", "B-2": "LEFT"}),
               "panel-sizes": compact_json({"A-1": 36, "B-2": 48}),
               "panel-element-positions": compact_json({"A-1": ns["WINDOWS10_ELEMENTS"], "B-2": []}),
               "panel-lengths": compact_json({"A-1": -1, "B-2": 100})})
        self.try_apply("macos")

    def test_7_9_lengths(self):
        self.assertEqual(self.panel_json("panel-lengths"), {"A-1": 100, "B-2": 100})


class MacosUserExtensionsDisabledTest(MacosTestCase):
    """8: disable-user-extensions = true → 書き込みなし"""

    def test_8_1_blocked_without_writes(self):
        self.setup_state([DOCK], disable_user=True)
        _written, error = self.try_apply("macos")
        self.assertPlainApplyError(error, ns["MSG_USER_EXTENSIONS_DISABLED"])
        self.assertEqual(self.writes, [])


class MacosRollbackTest(MacosTestCase):
    """9: Extension 一覧の書き込みを失敗させる（Dock・パネル・ArcMenu・ボタン配置は書いたあと）→ 元どおり"""

    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], PANEL, ARC],
                         **{"panel-positions": compact_json({"A-1": "BOTTOM"}),
                            "panel-element-positions": compact_json({"A-1": ns["WINDOWS11_ELEMENTS"]})})
        self.arc.set_string("menu-layout", "11")
        self.arc.set_string("position-in-panel", "Center")
        self.arc.set_string("force-menu-location", "BottomCentered")
        Gio.Settings.sync()
        self.before_layout = detect()
        self.before = self.user_values()
        self.writes.clear()

        orig = Gio.Settings.set_value

        def failing(settings, key, value):
            if key == "enabled-extensions":
                return False
            return orig(settings, key, value)
        Gio.Settings.set_value = failing
        try:
            self.written, self.error = self.try_apply("macos")
        finally:
            Gio.Settings.set_value = orig

    def test_9_1_failure_after_other_schemas_written(self):
        self.assertIsInstance(self.error, ns["ApplyWriteError"])
        written = {short_schema(s) for s, _k, meth in self.writes if meth == "set_value"}
        self.assertLessEqual({"dash-to-dock", "dash-to-panel", "arcmenu", "preferences"}, written)

    def test_9_2_restored_exactly(self):
        after = self.user_values()
        self.assertEqual({k: (v, after[k]) for k, v in self.before.items() if v != after[k]}, {})

    def test_9_3_no_pending_and_detect_unchanged(self):
        for settings in self.all_settings():
            self.assertFalse(settings.get_has_unapplied(), settings.props.schema_id)
        self.assertEqual(self.before_layout, "windows11")
        self.assertEqual(detect(), "windows11")


if __name__ == "__main__":
    unittest.main()
