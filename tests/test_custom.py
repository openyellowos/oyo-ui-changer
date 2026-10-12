"""
Custom 判定（2 段階方式）のテスト

  1. 既存の detect_layout() で候補を決める
  2. confirm_layout(候補): 候補の plan_layout() の変更予定が 0 件なら候補、1 件以上・計画の失敗なら custom

Phase 1（最小）
  A: 4 プリセットを Apply した状態 → 候補のまま一致                     4 件
  B: Original のアイコンサイズ 32 → 48 → custom → 再 Apply で Original   1 件
confirm_layout() の境界条件
  C: 計画を呼ばない候補 / 候補だけを調べる / 変更予定の数え方 /
     計画の失敗 / 書き込みをしない                                      11 件
実行: python3 -m unittest discover -s tests -v
"""

import unittest

from helpers import load_app  # noqa: F401  gi より先に読み込む（memory backend の強制）
from test_apply import DOCK, OTHERS, ApplyTestCase, detect, ns  # 読み込み済みのアプリと共通の前提づくり

from gi.repository import Gio, GLib  # noqa: E402  helpers のあとに読む


def confirm_layout(candidate):
    """アプリの confirm_layout()。まだなければ、未実装であることが分かる形で FAIL にする"""
    func = ns.get("confirm_layout")
    if func is None:
        raise AssertionError("confirm_layout() is not implemented in the app yet")
    return func(candidate)


def plan_changes(layout_id):
    """plan_layout() の変更予定（書き込みはしない）を [(スキーマ ID, キー), ...] で返す"""
    return [(settings.props.schema_id, key) for settings, changes in ns["plan_layout"](layout_id)
            for key, _value in changes]


class CustomTestCase(ApplyTestCase):
    def apply_preset(self, layout_id):
        """管理対象外の Extension を含む状態から、プリセットを Apply する"""
        self.setup_state([OTHERS[0], DOCK, OTHERS[1], OTHERS[2]])
        ns["apply_layout"](layout_id)
        self.writes.clear()


class PresetMatchesTest(CustomTestCase):
    """A: プリセットを Apply した直後は、候補（detect_layout）と計画 0 件が一致し、confirm_layout は候補を返す"""

    def assert_matches(self, layout_id):
        self.apply_preset(layout_id)
        self.assertEqual(detect(), layout_id)
        self.assertEqual(plan_changes(layout_id), [])
        self.assertEqual(confirm_layout(layout_id), layout_id)

    def test_a1_original(self):
        self.assert_matches("original")

    def test_a2_windows10(self):
        self.assert_matches("windows10")

    def test_a3_windows11(self):
        self.assert_matches("windows11")

    def test_a4_macos(self):
        self.assert_matches("macos")


class OriginalIconSizeTest(CustomTestCase):
    """B: Original のアイコンサイズを手で 32 → 48 にすると custom、Original を再 Apply すると元に戻る"""

    def test_b1_icon_size_custom_then_reapply(self):
        self.apply_preset("original")
        # 管理対象外の設定（Dock の autohide）も変えておき、再 Apply で触れないことを確かめる
        self.dock.set_boolean("autohide", not self.dock.get_boolean("autohide"))
        unmanaged_autohide = self.dock.get_boolean("autohide")
        self.dock.set_int("dash-max-icon-size", 48)
        Gio.Settings.sync()

        # 候補は Original のまま、変更予定はアイコンサイズだけ → custom
        self.assertEqual(detect(), "original")
        self.assertEqual(plan_changes("original"), [(ns["DOCK_SCHEMA"], "dash-max-icon-size")])
        self.assertEqual(confirm_layout("original"), "custom")

        # 同じプリセットを再 Apply → アイコンサイズだけを書き戻して Original に戻る
        self.writes.clear()
        ns["apply_layout"]("original")
        self.assertEqual(self.writes, [(ns["DOCK_SCHEMA"], "dash-max-icon-size", "set_value")])
        self.assertEqual(self.dock.get_int("dash-max-icon-size"), 32)
        self.assertEqual(confirm_layout("original"), "original")
        # 管理対象外の設定と Extension は保持
        self.assertEqual(self.dock.get_boolean("autohide"), unmanaged_autohide)
        self.assertEqual(self.shell.get_strv("enabled-extensions"), [OTHERS[0], DOCK, OTHERS[1], OTHERS[2]])


# Gio.Settings で設定を変えうるメソッド（判定中に 1 つも呼ばれないことを確かめる）
SETTINGS_WRITE_METHODS = ("set_value", "set_boolean", "set_double", "set_enum", "set_flags", "set_int", "set_int64",
                          "set_string", "set_strv", "set_uint", "set_uint64", "reset", "apply", "delay", "revert")


class ConfirmLayoutBoundaryTest(CustomTestCase):
    """C: confirm_layout() の境界条件"""

    def setUp(self):
        super().setUp()
        # plan_layout() の呼び出しを記録する（confirm_layout() はアプリの名前空間から plan_layout を引く）
        self.planned = []
        real_plan = ns["plan_layout"]

        def recording_plan(layout_id):
            self.planned.append(layout_id)
            return real_plan(layout_id)
        self.use_plan(recording_plan)

    def use_plan(self, plan):
        """このテストの間だけ plan_layout() を差し替える（終了時に元に戻す）"""
        self.addCleanup(ns.__setitem__, "plan_layout", ns["plan_layout"])
        ns["plan_layout"] = plan

    def stub_plan(self, result=None, error=None):
        """計画の中身や失敗を直接与える plan_layout()（呼び出しは記録する）"""
        def plan(layout_id):
            self.planned.append(layout_id)
            if error is not None:
                raise error
            return result
        self.use_plan(plan)

    # ---- 計画を呼ばない候補 ----
    def test_c01_custom_candidate_not_planned(self):
        self.assertEqual(confirm_layout("custom"), "custom")
        self.assertEqual(self.planned, [])

    def test_c02_unknown_candidates_not_planned(self):
        # "mixed" は detect_layout() の内部値、"11" / "windows" は ArcMenu 側の値
        for candidate in ("unknown", "mixed", "11", "windows", ""):
            with self.subTest(candidate=candidate):
                self.assertEqual(confirm_layout(candidate), "custom")
        self.assertEqual(self.planned, [])

    def test_c03_none_candidate_not_planned(self):
        self.assertEqual(confirm_layout(None), "custom")
        self.assertEqual(self.planned, [])

    # ---- 候補だけを調べる ----
    def test_c04_only_the_candidate_is_planned(self):
        for layout_id in ("original", "windows10", "windows11", "macos"):
            with self.subTest(layout_id=layout_id):
                self.apply_preset(layout_id)
                self.planned.clear()
                confirm_layout(layout_id)
                self.assertEqual(self.planned, [layout_id])

    def test_c05_other_matching_preset_is_not_checked(self):
        # 今の状態は Windows 10 と一致しているが、候補 Original の計画だけを見て custom を返す
        self.apply_preset("windows10")
        self.planned.clear()
        self.assertEqual(confirm_layout("original"), "custom")
        self.assertEqual(self.planned, ["original"])

    # ---- 変更予定の数え方 ----
    def test_c06_plan_with_only_empty_change_lists_matches(self):
        self.stub_plan(result=[(object(), []), (object(), []), (object(), [])])
        self.assertEqual(confirm_layout("windows11"), "windows11")

    def test_c07_one_change_in_last_schema_is_custom(self):
        self.stub_plan(result=[(object(), []), (object(), []), (object(), [("enabled-extensions", None)])])
        self.assertEqual(confirm_layout("windows11"), "custom")

    def test_c08_several_changes_are_custom(self):
        self.apply_preset("original")
        self.dock.set_int("dash-max-icon-size", 48)
        self.wm.set_string("button-layout", "close:")
        Gio.Settings.sync()
        self.assertEqual(len(plan_changes("original")), 2)
        self.assertEqual(confirm_layout("original"), "custom")

    # ---- 計画の失敗 ----
    def test_c09_apply_error_is_custom(self):
        # 実際の事前確認の失敗: disable-user-extensions=true / dash-to-panel の JSON が読めない
        # （前提づくりの Apply も plan_layout() を呼ぶため、記録は判定の直前に空にする）
        for label, break_settings in (
                ("disable-user-extensions", lambda: self.shell.set_boolean("disable-user-extensions", True)),
                ("broken panel-lengths", lambda: self.panel.set_string("panel-lengths", "{broken"))):
            with self.subTest(label):
                self.apply_preset("windows10")
                break_settings()
                Gio.Settings.sync()
                self.planned.clear()
                self.assertEqual(confirm_layout("windows10"), "custom")
                self.assertEqual(self.planned, ["windows10"])

    def test_c10_unexpected_errors_are_custom(self):
        for error in (RuntimeError("boom"), GLib.Error("boom"), KeyError("boom"), TypeError("boom")):
            with self.subTest(error=type(error).__name__):
                self.stub_plan(error=error)
                self.assertEqual(confirm_layout("macos"), "custom")

    # ---- 書き込みをしない ----
    def test_c11_no_settings_writes_while_confirming(self):
        calls = []
        for name in SETTINGS_WRITE_METHODS:
            orig = getattr(Gio.Settings, name)

            def spy(settings, *args, _orig=orig, _name=name):
                calls.append(_name)
                return _orig(settings, *args)
            setattr(Gio.Settings, name, spy)
            self.addCleanup(setattr, Gio.Settings, name, orig)
        # 一致する状態・一致しない状態の両方で、4 つの候補すべてを判定する
        self.apply_preset("macos")
        self.dock.set_int("dash-max-icon-size", 64)
        Gio.Settings.sync()
        before = self.user_values()
        calls.clear()
        self.writes.clear()
        for layout_id in ("original", "windows10", "windows11", "macos"):
            confirm_layout(layout_id)
        self.assertEqual(calls, [])
        self.assertEqual(self.writes, [])
        self.assertEqual(self.user_values(), before)
        for settings in self.all_settings():
            self.assertFalse(settings.get_has_unapplied(), settings.props.schema_id)


if __name__ == "__main__":
    unittest.main()
