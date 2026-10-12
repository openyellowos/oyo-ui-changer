"""
GUI のテスト（カード選択 → Apply → Current 表示・Apply ボタン・トーストを確かめる）

旧スクラッチテストを移したもの。入力と期待値は変えていない。
  uic-test12.py  Original → macOS → Windows 10 → Original                          4 件
  uic-test14.py  Original → Windows 11 → Windows 10 → Windows 11 → macOS → Original  6 件

旧テストと同じく、1 本の操作の流れの途中で状態を確かめる。
旧スクリプト 1 本につきアプリを 1 回動かし（setUpClass）、各チェック地点の状態を記録して、
テストメソッドで 1 件ずつ確かめる（どのメソッドを単独で実行しても、流れを最初から再現する）。

画面（Display）に実際に接続できない環境では skip する。接続できるのに失敗した場合は FAIL / ERROR にする。
設定は helpers の memory backend に書く（host の設定は変えない）。
実行: python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import unittest

from helpers import load_app  # gi より先に読み込む（memory backend の強制）

ns = load_app()

Gdk, Gio, GLib, Gtk = ns["Gdk"], ns["Gio"], ns["GLib"], ns["Gtk"]
DOCK = ns["DOCK_UUID"]

# 旧テストと同じ、操作の間隔
STEP_INTERVAL_MS = 300
# 操作が止まったときに打ち切るまでの時間（イベントループを終わらせ、テストを FAIL にする）
SCENARIO_TIMEOUT_S = 60

SCHEMAS = (
    (ns["SHELL_SCHEMA"], None),
    (ns["DOCK_SCHEMA"], DOCK),
    (ns["PANEL_SCHEMA"], ns["PANEL_UUID"]),
    (ns["ARCMENU_SCHEMA"], ns["ARCMENU_UUID"]),
    (ns["WM_SCHEMA"], None),
)


def display_available():
    """環境変数ではなく、実際に Display へ接続できるかで判定する"""
    try:
        Gtk.init_check()
    except Exception:  # noqa: BLE001 - 接続できない理由は問わない
        return False
    return Gdk.Display.get_default() is not None


def setup_settings():
    """
    開始状態: 完全な Original（旧テストの前提に Original を Apply したもの）。
    旧テストは Dock の有効化と位置だけの Original 相当で始めていたが、Custom 判定（confirm_layout）では
    管理対象のほかの設定が既定値のままだと custom になるため、Original を適用した状態から始める
    """
    for schema_id, uuid in SCHEMAS:
        settings = ns["open_settings"](schema_id, uuid)[0]
        for key in settings.props.settings_schema.list_keys():
            settings.reset(key)
    ns["open_settings"](ns["SHELL_SCHEMA"])[0].set_strv("enabled-extensions", ["ding@rastersoft.com", DOCK])
    ns["open_settings"](ns["DOCK_SCHEMA"], DOCK)[0].set_string("dock-position", "LEFT")
    Gio.Settings.sync()
    ns["apply_layout"]("original")


def view(app):
    """(current_layout, selected_layout, Current の印が出ているカード, Apply を押せるか)"""
    return (app.current_layout, app.selected_layout,
            [k for k, badge in app.current_badges.items() if badge.get_visible()],
            app.apply_button.get_sensitive())


def click(layout_id):
    return ("click", layout_id)


PRESS = ("press", None)


def check(label):
    return ("check", label)


def call(func):
    """任意の操作（func(app)）を 1 ステップとして実行する"""
    return ("call", func)


def run_scenario(steps, view_fn=view):
    """
    アプリを起動し、steps を STEP_INTERVAL_MS ごとに 1 つずつ実行する。
    戻り値: ({チェック名: (view_fn(app), 最後のトースト)}, 失敗の説明 or None)
    出したトーストの一覧は app.test_toasts で参照できる
    """
    setup_settings()
    app = ns["OyoUiChangerApp"]()
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    toasts = []
    app.test_toasts = toasts
    show_toast = app.show_toast
    app.show_toast = lambda message: (toasts.append(message), show_toast(message))
    results = {}
    failure = []
    sources = []

    def finish(a, reason=None):
        if reason is not None:
            failure.append(reason)
        for source_id in sources:
            GLib.source_remove(source_id)
        sources.clear()
        if a.window is not None:
            a.window.destroy()
        a.quit()

    def on_activate(a):
        it = iter(steps)

        def next_step():
            try:
                kind, arg = next(it)
            except StopIteration:
                finish(a)
                return False
            try:
                if kind == "click":
                    a.cards[arg].emit("clicked")
                elif kind == "press":
                    a.apply_button.emit("clicked")
                elif kind == "call":
                    arg(a)
                else:
                    results[arg] = (view_fn(a), toasts[-1:])
            except Exception as error:  # noqa: BLE001 - 例外はテストの失敗として報告する
                finish(a, f"{kind} {arg}: {type(error).__name__}: {error}")
                return False
            return True

        def on_timeout():
            sources.remove(timeout_id)
            finish(a, f"scenario did not finish within {SCENARIO_TIMEOUT_S}s")
            return False

        sources.append(GLib.timeout_add(STEP_INTERVAL_MS, next_step))
        timeout_id = GLib.timeout_add_seconds(SCENARIO_TIMEOUT_S, on_timeout)
        sources.append(timeout_id)

    app.connect("activate", on_activate)
    # アプリが起動時に出す状態表示はテストの出力に混ぜない
    with contextlib.redirect_stdout(io.StringIO()):
        app.run([])
    # 残ったイベントを処理して片付ける
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)
    return results, (failure[0] if failure else None)


class GuiScenarioTestCase(unittest.TestCase):
    STEPS = ()

    @classmethod
    def setUpClass(cls):
        # skip はクラス単位ではなく各テストで行い、件数（実行数・skip 数）に 1 件ずつ現れるようにする
        cls.display = display_available()
        if cls.display:
            cls.results, cls.failure = run_scenario(cls.STEPS)

    def setUp(self):
        if not self.display:
            self.skipTest("no display connection")

    def assertCheckpoint(self, label, expected_view, toast=None):
        """旧 exp(): view が一致し、toast が指定されていれば最後のトーストが一致する"""
        self.assertIsNone(self.failure)
        self.assertIn(label, self.results)
        got_view, last_toast = self.results[label]
        self.assertEqual(got_view, expected_view)
        if toast is not None:
            self.assertEqual(last_toast, [toast])


class GuiMacosWindows10Test(GuiScenarioTestCase):
    """旧 uic-test12.py: Original → macOS → Windows 10 → Original"""

    STEPS = (check("start"),
             click("macos"), PRESS, check("macOS Apply"),
             click("windows10"), PRESS, check("Windows 10 Apply"),
             click("original"), PRESS, check("back to Original"))

    def test_1_start(self):
        self.assertCheckpoint("start", ("original", "original", ["original"], False))

    def test_2_macos_apply(self):
        self.assertCheckpoint("macOS Apply", ("macos", "macos", ["macos"], False), "Applied macOS.")

    def test_3_windows10_apply(self):
        self.assertCheckpoint("Windows 10 Apply", ("windows10", "windows10", ["windows10"], False),
                              "Applied Windows 10.")

    def test_4_back_to_original(self):
        self.assertCheckpoint("back to Original", ("original", "original", ["original"], False),
                              "Applied oYo Original.")


class GuiAllLayoutsTest(GuiScenarioTestCase):
    """旧 uic-test14.py: Original → Windows 11 → Windows 10 → Windows 11 → macOS → Original"""

    STEPS = (check("start"),
             click("windows11"), PRESS, check("Windows 11 Apply"),
             click("windows10"), PRESS, check("Windows 10 Apply"),
             click("windows11"), PRESS, check("Windows 11 again"),
             click("macos"), PRESS, check("macOS Apply"),
             click("original"), PRESS, check("Original"))

    def test_1_start(self):
        self.assertCheckpoint("start", ("original", "original", ["original"], False))

    def test_2_windows11_apply(self):
        self.assertCheckpoint("Windows 11 Apply", ("windows11", "windows11", ["windows11"], False),
                              "Applied Windows 11.")

    def test_3_windows10_apply(self):
        self.assertCheckpoint("Windows 10 Apply", ("windows10", "windows10", ["windows10"], False),
                              "Applied Windows 10.")

    def test_4_windows11_again(self):
        self.assertCheckpoint("Windows 11 again", ("windows11", "windows11", ["windows11"], False),
                              "Applied Windows 11.")

    def test_5_macos_apply(self):
        self.assertCheckpoint("macOS Apply", ("macos", "macos", ["macos"], False), "Applied macOS.")

    def test_6_original(self):
        self.assertCheckpoint("Original", ("original", "original", ["original"], False), "Applied oYo Original.")


#----------------------------------------------------------------------------------------------------------------
# rollback が不完全なときの消えない警告（Adw.Banner）
#----------------------------------------------------------------------------------------------------------------
class FailureInjector:
    """
    シナリオの間だけ Gio.Settings.set_value を差し替え、Apply を意図的に失敗させる（memory backend 上）。
      mode None      : そのまま書く
      mode "write"   : 最初に書く dock-position で失敗する（まだ何も書いていない → ApplyWriteError）
      mode "rollback": Extension 一覧の書き込みで失敗し、rollback 中の dock-position の書き戻しも失敗する
                       （→ ApplyRollbackError。Original 相当の状態から macOS を適用したときに起きる）
    """

    def __init__(self):
        self.mode = None
        self.in_rollback = False
        self.real = None

    def install(self):
        self.real = Gio.Settings.set_value
        injector = self

        def fake(settings, key, value):
            if injector.mode == "write" and key == "dock-position":
                return False
            if injector.mode == "rollback" and key == "enabled-extensions":
                injector.in_rollback = True
                return False
            if injector.mode == "rollback" and injector.in_rollback and key == "dock-position":
                return False
            return injector.real(settings, key, value)
        Gio.Settings.set_value = fake

    def uninstall(self):
        Gio.Settings.set_value = self.real

    def mode_step(self, mode):
        """次の Apply の失敗のさせ方を決めるステップ（Apply ごとに状態を戻す）"""
        def step(_app):
            self.mode = mode
            self.in_rollback = False
        return call(step)


def settings_snapshot():
    """管理対象の 5 スキーマの全キーのユーザー値"""
    snapshot = {}
    for schema_id, uuid in SCHEMAS:
        settings = ns["open_settings"](schema_id, uuid)[0]
        for key in settings.props.settings_schema.list_keys():
            value = settings.get_user_value(key)
            snapshot[(schema_id, key)] = None if value is None else value.print_(True)
    return snapshot


def banner_view(app):
    banner = app.rollback_banner
    return {
        "current": app.current_layout,
        "live": ns["confirm_layout"](ns["detect_layout"](ns["read_current_state"]())),
        "badges": [k for k, badge in app.current_badges.items() if badge.get_visible()],
        "selected": app.selected_layout,
        "banner": banner.get_revealed(),
        "title": banner.get_title(),
        "button": banner.get_button_label(),
        "markup": banner.get_use_markup(),
        "toasts": list(app.test_toasts),
        "settings": settings_snapshot(),
    }


class BannerScenarioTestCase(GuiScenarioTestCase):
    INJECTOR = None

    @classmethod
    def setUpClass(cls):
        cls.display = display_available()
        if cls.display:
            cls.INJECTOR.install()
            try:
                cls.results, cls.failure = run_scenario(cls.STEPS, view_fn=banner_view)
            finally:
                cls.INJECTOR.uninstall()

    def state(self, label):
        self.assertIsNone(self.failure)
        self.assertIn(label, self.results)
        return self.results[label][0]


ROLLBACK_INJECTOR = FailureInjector()
BANNER_TEXT = ns["MSG_ROLLBACK_INCOMPLETE"]


class GuiRollbackBannerTest(BannerScenarioTestCase):
    """Original から始め、macOS の Apply で rollback を失敗させる"""

    INJECTOR = ROLLBACK_INJECTOR
    STEPS = (check("start"),
             ROLLBACK_INJECTOR.mode_step("rollback"), click("macos"), PRESS, check("rollback failed"),
             click("original"), check("card selected"),
             ROLLBACK_INJECTOR.mode_step("write"), PRESS, check("write failed"),
             ROLLBACK_INJECTOR.mode_step(None), PRESS, check("applied"),
             ROLLBACK_INJECTOR.mode_step("rollback"), click("macos"), PRESS, check("rollback failed again"),
             call(lambda a: a.rollback_banner.emit("button-clicked")), check("dismissed"),
             # Original に戻してから、もう一度 rollback を失敗させる
             ROLLBACK_INJECTOR.mode_step(None), click("original"), PRESS, check("restored after dismiss"),
             ROLLBACK_INJECTOR.mode_step("rollback"), click("macos"), PRESS, check("rollback failed after dismiss"),
             ROLLBACK_INJECTOR.mode_step(None))

    def test_b1_hidden_at_start_and_not_markup(self):
        s = self.state("start")
        self.assertIs(s["banner"], False)
        self.assertIs(s["markup"], False)
        self.assertEqual(s["title"], BANNER_TEXT)
        self.assertEqual(s["button"], "Dismiss")

    def test_b2_rollback_failure_shows_banner_without_toast(self):
        start, s = self.state("start"), self.state("rollback failed")
        self.assertIs(s["banner"], True)
        self.assertEqual(s["toasts"], start["toasts"])
        # 表示を読み直している（一部が戻らないので custom）
        self.assertEqual(s["current"], s["live"])
        self.assertEqual(s["current"], "custom")
        self.assertEqual(s["badges"], [])

    def test_b3_card_selection_keeps_banner(self):
        s = self.state("card selected")
        self.assertEqual(s["selected"], "original")
        self.assertIs(s["banner"], True)

    def test_b4_write_failure_uses_toast_and_keeps_banner(self):
        before, s = self.state("card selected"), self.state("write failed")
        self.assertEqual(s["toasts"], before["toasts"] + ["Failed to write dock-position"])
        self.assertIs(s["banner"], True)

    def test_b5_successful_apply_hides_banner(self):
        s = self.state("applied")
        self.assertIs(s["banner"], False)
        self.assertEqual(s["toasts"][-1], "Applied oYo Original.")
        self.assertEqual(s["current"], "original")

    def test_b6_rollback_failure_again_shows_banner(self):
        before, s = self.state("applied"), self.state("rollback failed again")
        self.assertIs(s["banner"], True)
        self.assertEqual(s["toasts"], before["toasts"])

    def test_b7_dismiss_hides_banner_without_changing_settings(self):
        before, s = self.state("rollback failed again"), self.state("dismissed")
        self.assertIs(s["banner"], False)
        self.assertEqual(s["settings"], before["settings"])
        self.assertEqual(s["toasts"], before["toasts"])
        self.assertEqual(s["current"], before["current"])

    def test_b8_shown_again_after_dismiss(self):
        restored = self.state("restored after dismiss")
        self.assertIs(restored["banner"], False)
        self.assertEqual(restored["current"], "original")
        s = self.state("rollback failed after dismiss")
        self.assertIs(s["banner"], True)
        self.assertEqual(s["toasts"], restored["toasts"])


NORMAL_FAILURE_INJECTOR = FailureInjector()


def set_user_extensions_disabled(disabled):
    def step(_app):
        ns["open_settings"](ns["SHELL_SCHEMA"])[0].set_boolean("disable-user-extensions", disabled)
        Gio.Settings.sync()
    return call(step)


class GuiNormalFailureNoBannerTest(BannerScenarioTestCase):
    """通常の Apply 失敗（ApplyWriteError / ApplyError）はトーストだけで、Banner は出さない"""

    INJECTOR = NORMAL_FAILURE_INJECTOR
    STEPS = (check("start"),
             NORMAL_FAILURE_INJECTOR.mode_step("write"), click("macos"), PRESS, check("write failed"),
             NORMAL_FAILURE_INJECTOR.mode_step(None), set_user_extensions_disabled(True), PRESS,
             check("preflight failed"),
             set_user_extensions_disabled(False))

    def test_n1_write_failure_toast_only(self):
        start, s = self.state("start"), self.state("write failed")
        self.assertEqual(s["toasts"], start["toasts"] + ["Failed to write dock-position"])
        self.assertIs(s["banner"], False)
        self.assertEqual(s["current"], "original")

    def test_n2_preflight_failure_toast_only(self):
        before, s = self.state("write failed"), self.state("preflight failed")
        self.assertEqual(s["toasts"], before["toasts"] + [ns["MSG_USER_EXTENSIONS_DISABLED"]])
        self.assertIs(s["banner"], False)


if __name__ == "__main__":
    unittest.main()
