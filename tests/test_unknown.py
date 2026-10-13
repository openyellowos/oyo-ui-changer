"""
状態を確認できない（unknown）の判定のテスト（Startup Exception Safety Phase 1。GUI にはまだ接続しない）

  normal : 判定に必要な値が読め、プリセットに一致する
  custom : 判定に必要な値は読めたが、プリセットに一致しない
  unknown: 判定に必要な値が読めない、または判定中に想定外の例外が起きた

  U: unreadable_reason()（偽の状態を渡す。設定の読み書きはしない）
       必要な値がそろった状態（test_detect の 25 件）/ shell の 3 項目 / dock・panel の状態項目 /
       有効な Extension の値 / 未インストール・無効の Extension                      9 件
  S: assess_layout()（memory backend の実際の設定を読む）
       4 プリセット / 正常な custom / ApplyError は custom / 読み取りの失敗 /
       想定外の例外 / 書き込みをしない                                              10 件
実行: python3 -m unittest discover -s tests -v
"""

import unittest

from helpers import load_app  # noqa: F401  gi より先に読み込む（memory backend の強制）
from test_apply import DOCK, OTHERS, ApplyTestCase, ns  # 読み込み済みのアプリと共通の前提づくり
from test_detect import CASES, DTP, J, el, mk

from gi.repository import Gio, GLib  # noqa: E402  helpers のあとに読む

unreadable_reason = ns["unreadable_reason"]
UNKNOWN = ns["LAYOUT_UNKNOWN"]
# 判定に必要な値が欠けている test_detect の 4 件（26〜29。期待値はどれも custom）
NONE_CASE_NAMES = ("NONE enabled-extensions", "NONE dock-position", "NONE panel-positions (windows)",
                   "NONE missing dash-to-panel entry")


def with_none(state, name, key):
    state[name]["keys"][key]["value"] = None
    return state


class UnreadableReasonTest(unittest.TestCase):
    """U: 判定に必要な値が読めているかだけを見る（値の中身は見ない）"""

    def assertReadable(self, state):
        self.assertIsNone(unreadable_reason(state))

    def assertUnreadable(self, state, words):
        reason = unreadable_reason(state)
        self.assertIsInstance(reason, str)
        for word in words:
            self.assertIn(word, reason)

    def test_u1_detect_cases_with_all_values_are_readable(self):
        # 4 レイアウトと正常な custom（壊れた JSON・無効・未インストールなど）の 25 件は、そろっている
        readable = [(name, state) for name, state, _expected in CASES if name not in NONE_CASE_NAMES]
        self.assertEqual(len(readable), 25)
        for name, state in readable:
            with self.subTest(name):
                self.assertReadable(state)

    def test_u2_detect_none_cases_are_unreadable(self):
        none_cases = [(name, state) for name, state, _expected in CASES if name in NONE_CASE_NAMES]
        self.assertEqual(len(none_cases), 4)
        for name, state in none_cases:
            with self.subTest(name):
                self.assertIsInstance(unreadable_reason(state), str)

    def test_u3_each_shell_key_is_required(self):
        for key in ("enabled-extensions", "disabled-extensions", "disable-user-extensions"):
            with self.subTest(key):
                self.assertUnreadable(with_none(mk([DOCK]), "shell", key), ("shell", key))

    def test_u4_shell_entry_missing_or_broken(self):
        state = mk([DOCK])
        del state["shell"]
        self.assertUnreadable(state, ("shell",))
        state = mk([DOCK])
        state["shell"] = None
        self.assertUnreadable(state, ("shell",))

    def test_u5_dock_and_panel_entries_are_required(self):
        for name in ("dash-to-dock", "dash-to-panel"):
            for label, broken in (("missing", None), ("not a dict", "x"), ("no uuid", "no-uuid")):
                with self.subTest(name=name, case=label):
                    state = mk([DOCK])
                    if broken is None:
                        del state[name]
                    elif broken == "no-uuid":
                        state[name]["uuid"] = None
                    else:
                        state[name] = broken
                    self.assertUnreadable(state, (name,))

    def test_u6_enabled_extension_values_are_required(self):
        cases = (
            (mk([DOCK]), "dash-to-dock", "dock-position"),
            (mk([DTP]), "dash-to-panel", "panel-positions"),
            (mk([DTP]), "dash-to-panel", "panel-element-positions"),
            # macOS（両方有効）では、どちらの値も必要
            (mk([DTP, DOCK], dock_pos="BOTTOM", positions=J({"0": "TOP"})), "dash-to-dock", "dock-position"),
            (mk([DTP, DOCK], dock_pos="BOTTOM", positions=J({"0": "TOP"})), "dash-to-panel", "panel-positions"),
        )
        for state, name, key in cases:
            with self.subTest(name=name, key=key):
                self.assertUnreadable(with_none(state, name, key), (name, key))
        # 値の入れ物（keys）ごとない場合も読めていない
        state = mk([DOCK])
        del state["dash-to-dock"]["keys"]
        self.assertUnreadable(state, ("dash-to-dock", "dock-position"))

    def test_u7_values_of_inactive_extensions_are_not_required(self):
        # 未インストール・無効の Extension の値は判定に使わないので、読めなくても unknown にしない
        cases = (
            ("dock not installed (in enabled list)", mk([DOCK, DTP], installed=("panel", "arc")), "dash-to-dock"),
            ("panel not installed (in enabled list)", mk([DOCK, DTP], installed=("dock",)), "dash-to-panel"),
            ("dock not in enabled list", mk([DTP]), "dash-to-dock"),
            ("panel not in enabled list", mk([DOCK]), "dash-to-panel"),
            ("dock in disabled-extensions", mk([DOCK, DTP], disabled=[DOCK]), "dash-to-dock"),
            ("disable-user-extensions true", mk([DOCK, DTP], disable_user=True), "dash-to-panel"),
        )
        for label, state, name in cases:
            with self.subTest(label):
                for key in list(state[name]["keys"]):
                    with_none(state, name, key)
                self.assertReadable(state)

    def test_u8_content_is_not_checked(self):
        # 読めた値の中身が壊れている・一致しないのは custom の範囲（unknown にしない）
        for state in (mk([DTP], positions="{not json"), mk([DTP], positions=J({"A": "BOTTOM", "B": "TOP"})),
                      mk([DTP], elements=J({"0": el("stackedBR")})), mk([DOCK], dock_pos="RIGHT")):
            self.assertReadable(state)
            self.assertEqual(ns["detect_layout"](state), "custom")

    def test_u9_not_a_state(self):
        for state in (None, [], "state"):
            with self.subTest(state=state):
                self.assertUnreadable(state, ())


class AssessLayoutTest(ApplyTestCase):
    """S: 読み取りから判定までをまとめた assess_layout()（memory backend の実際の設定）"""

    def setUp(self):
        super().setUp()
        self.planned = []

    def assess(self, state_reader=None):
        return ns["assess_layout"]() if state_reader is None else ns["assess_layout"](state_reader)

    def apply_preset(self, layout_id):
        self.setup_state([OTHERS[0], DOCK, OTHERS[1], OTHERS[2]])
        ns["apply_layout"](layout_id)
        Gio.Settings.sync()
        self.writes.clear()

    def replace(self, name, func):
        """このテストの間だけアプリの関数を差し替える（終了時に元に戻す）"""
        self.addCleanup(ns.__setitem__, name, ns[name])
        ns[name] = func

    def raising(self, error):
        def func(*_args):
            raise error
        return func

    def assertUnknown(self, result, words=()):
        layout, reason = result
        self.assertEqual(layout, UNKNOWN)
        self.assertIsInstance(reason, str)
        for word in words:
            self.assertIn(word, reason)

    def test_s01_four_presets_are_normal(self):
        for layout_id in ("original", "windows10", "windows11", "macos"):
            with self.subTest(layout_id):
                self.apply_preset(layout_id)
                self.assertEqual(self.assess(), (layout_id, None))

    def test_s02_changed_managed_setting_is_custom(self):
        self.apply_preset("original")
        self.dock.set_int("dash-max-icon-size", 48)
        Gio.Settings.sync()
        self.assertEqual(self.assess(), ("custom", None))

    def test_s03_structural_custom_is_custom(self):
        cases = (
            ("plain GNOME (no dock / panel)", lambda: self.setup_state(["ding@rastersoft.com"])),
            ("dock RIGHT", lambda: self.setup_state([DOCK], dock_pos="RIGHT")),
            ("broken panel-positions", lambda: self.setup_state([ns["PANEL_UUID"]], panel_json="{broken")),
            ("dock in disabled-extensions", lambda: self.setup_state([DOCK], disabled=[DOCK])),
        )
        for label, make in cases:
            with self.subTest(label):
                make()
                self.assertEqual(self.assess(), ("custom", None))

    def test_s04_apply_error_stays_custom(self):
        # 事前確認の失敗（ApplyError）は従来どおり custom
        for label, break_settings in (
                ("disable-user-extensions", lambda: self.shell.set_boolean("disable-user-extensions", True)),
                ("broken panel-lengths", lambda: self.panel.set_string("panel-lengths", "{broken"))):
            with self.subTest(label):
                self.apply_preset("windows10")
                break_settings()
                Gio.Settings.sync()
                self.assertEqual(self.assess(), ("custom", None))

    def test_s05_reader_errors_are_unknown(self):
        for error in (RuntimeError("boom"), GLib.Error("boom"), KeyError("boom"), TypeError("boom")):
            with self.subTest(error=type(error).__name__):
                self.assertUnknown(self.assess(self.raising(error)), ("unexpected error", type(error).__name__))

    def test_s06_unreadable_values_are_unknown(self):
        self.apply_preset("original")
        real_reader = ns["read_current_state"]
        cases = (
            ("shell", "enabled-extensions"),
            ("shell", "disabled-extensions"),
            ("shell", "disable-user-extensions"),
            ("dash-to-dock", "dock-position"),  # Original では dock が有効
        )
        for name, key in cases:
            with self.subTest(name=name, key=key):
                def reader(name=name, key=key):
                    return with_none(real_reader(), name, key)
                self.assertUnknown(self.assess(reader), (name, key))
        # reader が状態の形をしていないものを返した
        self.assertUnknown(self.assess(lambda: None))

    def test_s07_detect_errors_are_unknown(self):
        self.apply_preset("macos")
        for name in ("unreadable_reason", "detect_layout", "confirm_layout"):
            with self.subTest(name):
                real = ns[name]
                ns[name] = self.raising(RuntimeError("boom"))
                try:
                    self.assertUnknown(self.assess(), ("unexpected error", "RuntimeError"))
                finally:
                    ns[name] = real  # 次の関数を調べる前に戻す（前の関数で止まらないように）
                self.assertEqual(self.assess(), ("macos", None))

    def test_s08_unexpected_plan_errors_are_unknown(self):
        # confirm_layout() の計画の途中の想定外の例外（ApplyError 以外）は unknown
        self.apply_preset("macos")
        for error in (RuntimeError("boom"), GLib.Error("boom"), KeyError("boom"), TypeError("boom")):
            with self.subTest(error=type(error).__name__):
                self.replace("plan_layout", self.raising(error))
                self.assertUnknown(self.assess(), ("could not be confirmed",))

    def test_s09_recovers_when_reading_works_again(self):
        # 読めなかった後でも、読めるようになれば通常どおり判定する（状態を持ち越さない）
        self.apply_preset("windows11")
        self.assertUnknown(self.assess(self.raising(RuntimeError("boom"))))
        self.assertEqual(self.assess(), ("windows11", None))

    def test_s10_no_settings_writes(self):
        self.apply_preset("macos")
        self.dock.set_int("dash-max-icon-size", 64)
        Gio.Settings.sync()
        before = self.user_values()
        self.writes.clear()
        real_reader = ns["read_current_state"]
        readers = (
            None,
            self.raising(RuntimeError("boom")),
            lambda: with_none(real_reader(), "shell", "enabled-extensions"),
        )
        for reader in readers:
            self.assess(reader)
        self.replace("plan_layout", self.raising(RuntimeError("boom")))
        self.assess()
        self.assertEqual(self.writes, [])
        self.assertEqual(self.user_values(), before)
        for settings in self.all_settings():
            self.assertFalse(settings.get_has_unapplied(), settings.props.schema_id)


if __name__ == "__main__":
    unittest.main()
