"""
rollback の失敗検知のテスト（memory backend のみ。実際の GNOME 設定には書き込まない）

  R: rollback(written) が、戻せなかった・確かめられなかったキーを返す
     （set_value の False / reset の例外 / 値が変わらない / apply・sync の例外 / 重複 / ユーザー値の有無）
  A: apply_plan() の失敗時に、rollback が不完全なら ApplyRollbackError、完全なら従来どおり ApplyWriteError
実行: python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import unittest

from helpers import load_app  # noqa: F401  gi より先に読み込む（memory backend の強制）
from test_apply import DOCK, OTHERS, PANEL, ApplyTestCase, ns  # 読み込み済みのアプリと共通の前提づくり

from gi.repository import Gio, GLib  # noqa: E402  helpers のあとに読む


class RollbackTestCase(ApplyTestCase):
    def setUp(self):
        super().setUp()
        self.setup_state([OTHERS[0], DOCK, OTHERS[1]], dock_pos="RIGHT", button="close:")
        # 管理対象外の設定（rollback で触れないことを確かめる）
        self.dock.set_boolean("autohide", True)
        Gio.Settings.sync()
        self.writes.clear()

    def patch(self, cls_or_obj, name, replacement):
        """このテストの間だけ差し替える（終了時に元に戻す）"""
        original = getattr(cls_or_obj, name)
        self.addCleanup(setattr, cls_or_obj, name, original)
        setattr(cls_or_obj, name, replacement)
        return original

    def write_like_apply(self, changes):
        """apply_plan() と同じ手順で書き、rollback 用の written を返す"""
        written = []
        for settings, key, value in changes:
            written.append((settings, key, settings.get_user_value(key)))
            settings.delay()
            self.assertTrue(settings.set_value(key, value))
            settings.apply()
        Gio.Settings.sync()
        return written

    def standard_written(self):
        """ユーザー値あり（dock-position, button-layout）とユーザー値なし（dash-max-icon-size）を書き換える"""
        return self.write_like_apply([
            (self.dock, "dock-position", GLib.Variant("s", "LEFT")),
            (self.dock, "dash-max-icon-size", GLib.Variant("i", 48)),
            (self.wm, "button-layout", GLib.Variant("s", "appmenu:minimize,maximize,close")),
        ])

    def rollback(self, written):
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            failed = ns["rollback"](written)
        return failed, log.getvalue()

    def assert_restored(self, keys=("dock-position", "dash-max-icon-size", "button-layout")):
        expected = {"dock-position": ("dock", "RIGHT"), "dash-max-icon-size": ("dock", None), "button-layout": ("wm", "close:")}
        for key in keys:
            name, value = expected[key]
            user = getattr(self, name).get_user_value(key)
            with self.subTest(key=key):
                self.assertEqual(None if user is None else user.unpack(), value)

    def assert_unmanaged_untouched(self):
        self.assertIs(self.dock.get_boolean("autohide"), True)
        self.assertEqual(self.shell.get_strv("enabled-extensions"), [OTHERS[0], DOCK, OTHERS[1]])


DOCK_KEY = lambda key: (ns["DOCK_SCHEMA"], key)  # noqa: E731
WM_KEY = lambda key: (ns["WM_SCHEMA"], key)  # noqa: E731


class RollbackDetectionTest(RollbackTestCase):
    """R: rollback() の戻り値（戻せなかったキー）"""

    def test_r01_all_restored(self):
        failed, log = self.rollback(self.standard_written())
        self.assertEqual(failed, [])
        self.assertEqual(log, "")
        self.assert_restored()
        self.assert_unmanaged_untouched()

    def test_r02_set_value_false_detected_and_others_restored(self):
        written = self.standard_written()
        real = Gio.Settings.set_value
        self.patch(Gio.Settings, "set_value",
                   lambda s, key, value: False if key == "dock-position" else real(s, key, value))
        failed, log = self.rollback(written)
        self.assertEqual(failed, [DOCK_KEY("dock-position")])
        self.assertIn("rollback failed: " + ns["DOCK_SCHEMA"] + " dock-position: write rejected", log)
        self.assert_restored(("dash-max-icon-size", "button-layout"))
        self.assert_unmanaged_untouched()

    def test_r03_reset_exception_detected_and_others_restored(self):
        written = self.standard_written()
        real = Gio.Settings.reset

        def failing_reset(s, key):
            if key == "dash-max-icon-size":
                raise RuntimeError("reset boom")
            return real(s, key)
        self.patch(Gio.Settings, "reset", failing_reset)
        failed, log = self.rollback(written)
        self.assertEqual(failed, [DOCK_KEY("dash-max-icon-size")])
        self.assertIn("reset boom", log)
        self.assert_restored(("dock-position", "button-layout"))

    def test_r04_reported_success_but_value_unchanged(self):
        written = self.standard_written()
        real = Gio.Settings.set_value
        # 成功を返すが書かない
        self.patch(Gio.Settings, "set_value",
                   lambda s, key, value: True if key == "button-layout" else real(s, key, value))
        failed, log = self.rollback(written)
        self.assertEqual(failed, [WM_KEY("button-layout")])
        self.assertIn("not restored", log)
        self.assert_restored(("dock-position", "dash-max-icon-size"))

    def test_r05_reset_without_effect_detected(self):
        # ユーザー値がなかったキー: reset しても値が残っていれば失敗
        written = self.standard_written()
        real = Gio.Settings.reset
        self.patch(Gio.Settings, "reset", lambda s, key: None if key == "dash-max-icon-size" else real(s, key))
        failed, _log = self.rollback(written)
        self.assertEqual(failed, [DOCK_KEY("dash-max-icon-size")])
        self.assert_restored(("dock-position", "button-layout"))

    def test_r06_apply_exception_marks_that_schema_unconfirmed(self):
        written = self.standard_written()
        real = Gio.Settings.apply

        def failing_apply(s):
            if s.props.schema_id == ns["DOCK_SCHEMA"]:
                raise RuntimeError("apply boom")
            return real(s)
        self.patch(Gio.Settings, "apply", failing_apply)
        failed, log = self.rollback(written)
        self.assertEqual(sorted(failed), sorted([DOCK_KEY("dock-position"), DOCK_KEY("dash-max-icon-size")]))
        self.assertIn("apply failed: apply boom", log)
        self.assert_restored(("button-layout",))

    def test_r07_sync_exception_marks_all_unconfirmed(self):
        written = self.standard_written()
        self.patch(Gio.Settings, "sync", staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("sync boom"))))
        failed, log = self.rollback(written)
        self.assertEqual(sorted(failed), sorted([DOCK_KEY("dock-position"), DOCK_KEY("dash-max-icon-size"),
                                                 WM_KEY("button-layout")]))
        self.assertIn("sync failed: sync boom", log)

    def test_r08_failed_keys_are_unique(self):
        # 同じキーが 2 回記録され、書き戻しも確認も失敗する → 一覧には 1 回だけ
        written = self.standard_written()
        written = written + [written[0]]
        self.patch(Gio.Settings, "set_value", lambda s, key, value: False)
        failed, _log = self.rollback(written)
        self.assertEqual(len(failed), len(set(failed)))
        self.assertIn(DOCK_KEY("dock-position"), failed)
        self.assertIn(WM_KEY("button-layout"), failed)
        self.assertNotIn(DOCK_KEY("dash-max-icon-size"), failed)  # reset で戻ったキーは含まない

    def test_r09_user_value_presence_is_verified(self):
        # 元はユーザー値なし → reset 後もユーザー値なし。元はユーザー値あり → 同じ値のユーザー値
        written = self.standard_written()
        self.assertIsNone(written[1][2])
        self.assertIsNotNone(written[0][2])
        failed, _log = self.rollback(written)
        self.assertEqual(failed, [])
        self.assertIsNone(self.dock.get_user_value("dash-max-icon-size"))
        self.assertEqual(self.dock.get_user_value("dock-position").unpack(), "RIGHT")


class ApplyPlanRollbackTest(RollbackTestCase):
    """A: apply_plan() の失敗時の例外（Original を適用し、最後の Extension 一覧の書き込みで失敗させる）"""

    def setUp(self):
        super().setUp()
        # Windows 相当から Original へ（Dock・ボタン配置を書いたあと、Extension 一覧で失敗）
        self.setup_state([OTHERS[0], PANEL, OTHERS[1]], dock_pos="RIGHT", button="close:")
        self.dock.set_boolean("autohide", True)
        Gio.Settings.sync()
        self.before = self.user_values()
        self.writes.clear()
        self.in_rollback = False

    def fail_extension_list(self, rollback_fail_key=None, error=None):
        """enabled-extensions の書き込みで失敗させ、以後（rollback 中）は rollback_fail_key の書き戻しも失敗させる"""
        real = Gio.Settings.set_value

        def fake(s, key, value):
            if key == "enabled-extensions":
                self.in_rollback = True
                if error is not None:
                    raise error
                return False
            if self.in_rollback and key == rollback_fail_key:
                return False
            return real(s, key, value)
        self.patch(Gio.Settings, "set_value", fake)

    def apply_original(self):
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                ns["apply_layout"]("original")
            except ns["ApplyError"] as error:
                return error
        self.fail("apply_layout did not fail")

    def changed_user_values(self):
        after = self.user_values()
        return {k: (v, after[k]) for k, v in self.before.items() if v != after[k]}

    def test_a1_rollback_success_keeps_apply_write_error(self):
        self.fail_extension_list()
        error = self.apply_original()
        self.assertIs(type(error), ns["ApplyWriteError"])
        self.assertEqual(str(error), "Failed to write enabled-extensions")
        self.assertEqual(self.changed_user_values(), {})

    def test_a2_rollback_failure_raises_apply_rollback_error(self):
        self.fail_extension_list(rollback_fail_key="dock-position")
        error = self.apply_original()
        self.assertIs(type(error), ns["ApplyRollbackError"])
        self.assertIsInstance(error, ns["ApplyWriteError"])
        self.assertIsInstance(error, ns["ApplyError"])
        self.assertEqual(error.failed, [DOCK_KEY("dock-position")])
        self.assertEqual(str(error), "Failed to write enabled-extensions")
        self.assertIsInstance(error.__cause__, ns["ApplyWriteError"])
        self.assertEqual(str(error.__cause__), "Failed to write enabled-extensions")
        # 戻せなかった dock-position 以外は元どおり、管理対象外も変わらない
        changed = self.changed_user_values()
        self.assertEqual(list(changed), [(ns["DOCK_SCHEMA"], "dock-position")])
        self.assertIs(self.dock.get_boolean("autohide"), True)
        self.assertEqual(self.shell.get_strv("enabled-extensions"), [OTHERS[0], PANEL, OTHERS[1]])

    def test_a3_unexpected_error_with_rollback_failure_keeps_cause(self):
        self.fail_extension_list(rollback_fail_key="dock-position", error=TypeError("boom"))
        error = self.apply_original()
        self.assertIs(type(error), ns["ApplyRollbackError"])
        self.assertEqual(str(error), "Failed to apply the layout: boom")
        self.assertIsInstance(error.__cause__, TypeError)

    def test_a4_unexpected_error_with_rollback_success_unchanged(self):
        self.fail_extension_list(error=TypeError("boom"))
        error = self.apply_original()
        self.assertIs(type(error), ns["ApplyWriteError"])
        self.assertEqual(str(error), "Failed to apply the layout: boom")
        self.assertIsInstance(error.__cause__, TypeError)
        self.assertEqual(self.changed_user_values(), {})

    def test_a5_rollback_crash_keeps_original_failure(self):
        self.fail_extension_list()
        self.addCleanup(ns.__setitem__, "rollback", ns["rollback"])
        ns["rollback"] = lambda written: (_ for _ in ()).throw(RuntimeError("rollback crashed"))
        error = self.apply_original()
        self.assertIs(type(error), ns["ApplyRollbackError"])
        self.assertEqual(str(error), "Failed to write enabled-extensions")
        self.assertIsInstance(error.__cause__, ns["ApplyWriteError"])
        # Dock とボタン配置は書いたあとなので、全部「確かめられなかった」として返る
        self.assertEqual(sorted(error.failed), sorted(set(error.failed)))
        self.assertIn(DOCK_KEY("dock-position"), error.failed)
        self.assertIn(WM_KEY("button-layout"), error.failed)

    def test_a6_successful_apply_does_not_roll_back(self):
        calls = []
        real = ns["rollback"]
        self.addCleanup(ns.__setitem__, "rollback", real)
        ns["rollback"] = lambda written: (calls.append(written), real(written))[1]
        written = ns["apply_layout"]("original")
        self.assertTrue(written)
        self.assertEqual(calls, [])
        self.assertEqual(ns["confirm_layout"](ns["detect_layout"](ns["read_current_state"]())), "original")


if __name__ == "__main__":
    unittest.main()
