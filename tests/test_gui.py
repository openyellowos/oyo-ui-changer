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


# unknown の警告の「再確認」を押す
CHECK_AGAIN = call(lambda a: a.unknown_banner.emit("button-clicked"))


def run_scenario(steps, view_fn=view, state_reader=None):
    """
    アプリを起動し、steps を STEP_INTERVAL_MS ごとに 1 つずつ実行する。
    state_reader を渡すと、アプリはそれで設定を読み取る（読み取りの失敗を起こすため）。
    戻り値: ({チェック名: (view_fn(app), 最後のトースト)}, 失敗の説明 or None)
    出したトーストの一覧は app.test_toasts で参照できる
    """
    setup_settings()
    app = ns["OyoUiChangerApp"]() if state_reader is None else ns["OyoUiChangerApp"](state_reader=state_reader)
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    toasts = []
    app.test_toasts = toasts
    log = io.StringIO()
    app.test_log = log  # アプリが標準出力に出したログ
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
    # アプリが起動時に出す状態表示はテストの出力に混ぜない（app.test_log で参照できる）
    with contextlib.redirect_stdout(log):
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


#----------------------------------------------------------------------------------------------------------------
# 想定外の例外・表示の読み直しの失敗（GUI Exception Safety）
#----------------------------------------------------------------------------------------------------------------
# 例外の中身（画面に出てはいけない。ログには残る）
SECRET_DETAIL = "internal-detail-7f3a"
MSG_A = ns["MSG_UNEXPECTED_APPLY_ERROR"]
MSG_B = ns["MSG_LAYOUT_CHECK_FAILED"]


class FaultController:
    """
    シナリオの間だけ、次の失敗を起こせるようにする（ステップで切り替える）。
      preflight_raise: このレイアウトの計画（事前確認）で想定外の例外を出す
      refresh_fails  : 表示の読み直し（refresh_current_layout）で例外を出す
    Apply の書き込みの失敗は FailureInjector で起こす
    """

    def __init__(self):
        self.preflight_raise = set()
        self.refresh_fails = False
        self.injector = FailureInjector()

    def install(self):
        app_class = ns["OyoUiChangerApp"]
        self.real_refresh = app_class.refresh_current_layout
        self.real_planners = dict(ns["LAYOUT_PLANNERS"])
        controller = self

        def refresh(app_self):
            if controller.refresh_fails:
                raise RuntimeError(SECRET_DETAIL)
            return controller.real_refresh(app_self)
        app_class.refresh_current_layout = refresh

        def planner_for(layout_id, real):
            def planner():
                if layout_id in controller.preflight_raise:
                    raise RuntimeError(SECRET_DETAIL)
                return real()
            return planner
        for layout_id, real in self.real_planners.items():
            ns["LAYOUT_PLANNERS"][layout_id] = planner_for(layout_id, real)
        self.injector.install()

    def uninstall(self):
        self.injector.uninstall()
        ns["LAYOUT_PLANNERS"].clear()
        ns["LAYOUT_PLANNERS"].update(self.real_planners)
        ns["OyoUiChangerApp"].refresh_current_layout = self.real_refresh

    def set(self, preflight_raise=(), refresh_fails=False, write_mode=None):
        """次の Apply のための失敗の設定（Apply ごとに書き込みの失敗の状態も戻す）"""
        def step(_app):
            self.preflight_raise = set(preflight_raise)
            self.refresh_fails = refresh_fails
            self.injector.mode = write_mode
            self.injector.in_rollback = False
        return call(step)


def fault_view(app):
    return {
        "current": app.current_layout,
        "banner": app.rollback_banner.get_revealed(),
        "unknown": app.unknown_banner.get_revealed(),
        "toasts": list(app.test_toasts),
        "log": app.test_log.getvalue(),
        "settings": settings_snapshot(),
    }


class FaultScenarioTestCase(GuiScenarioTestCase):
    CONTROLLER = None

    @classmethod
    def setUpClass(cls):
        cls.display = display_available()
        if cls.display:
            cls.CONTROLLER.install()
            try:
                cls.results, cls.failure = run_scenario(cls.STEPS, view_fn=fault_view)
            finally:
                cls.CONTROLLER.uninstall()

    def state(self, label):
        self.assertIsNone(self.failure)
        self.assertIn(label, self.results)
        return self.results[label][0]

    def assertNoDetailOnScreen(self, s):
        for toast in s["toasts"]:
            self.assertNotIn(SECRET_DETAIL, toast)
            self.assertNotIn("RuntimeError", toast)
            self.assertNotIn("Traceback", toast)


UNEXPECTED = FaultController()


class GuiUnexpectedErrorTest(FaultScenarioTestCase):
    """事前確認での想定外の例外（Banner なし／Banner 表示中）"""

    CONTROLLER = UNEXPECTED
    STEPS = (check("start"),
             UNEXPECTED.set(preflight_raise={"macos"}), click("macos"), PRESS, check("preflight error"),
             # その後の Apply は普通に成功する（アプリは動き続ける）
             UNEXPECTED.set(), click("windows10"), PRESS, check("later apply"),
             # macOS で rollback に失敗して Banner を出したあと（macOS を選んだまま）、想定外の例外
             UNEXPECTED.set(write_mode="rollback"), click("macos"), PRESS, check("banner shown"),
             UNEXPECTED.set(preflight_raise={"macos"}), PRESS, check("error while banner shown"),
             UNEXPECTED.set())

    def test_u1_toast_a_only_and_nothing_changed(self):
        start, s = self.state("start"), self.state("preflight error")
        self.assertEqual(s["toasts"], start["toasts"] + [MSG_A])
        self.assertIs(s["banner"], False)
        self.assertEqual(s["settings"], start["settings"])
        self.assertEqual(s["current"], start["current"])

    def test_u2_details_in_log_not_on_screen(self):
        s = self.state("preflight error")
        self.assertNoDetailOnScreen(s)
        self.assertIn("Traceback", s["log"])
        self.assertIn(SECRET_DETAIL, s["log"])

    def test_u3_app_keeps_working(self):
        s = self.state("later apply")
        self.assertEqual(s["toasts"][-1], "Applied Windows 10.")
        self.assertEqual(s["current"], "windows10")

    def test_u4_banner_kept_when_unexpected_error(self):
        shown, s = self.state("banner shown"), self.state("error while banner shown")
        self.assertIs(shown["banner"], True)
        self.assertIs(s["banner"], True)
        self.assertEqual(s["toasts"], shown["toasts"] + [MSG_A])
        self.assertEqual(s["settings"], shown["settings"])
        self.assertNoDetailOnScreen(s)


REFRESH = FaultController()


class GuiRefreshFailureTest(FaultScenarioTestCase):
    """
    表示の読み直しに失敗したとき（Apply 成功後／ApplyWriteError 後／rollback 失敗と同時）。
    読み直しに失敗すると unknown になり Apply できないので、次の Apply の前に「再確認」で確認できる状態に戻す
    """

    CONTROLLER = REFRESH
    STEPS = (check("start"),
             REFRESH.set(refresh_fails=True), click("windows10"), PRESS, check("success, refresh failed"),
             REFRESH.set(), CHECK_AGAIN,
             REFRESH.set(refresh_fails=True, write_mode="write"), click("macos"), PRESS, check("write error, refresh failed"),
             REFRESH.set(), CHECK_AGAIN,
             REFRESH.set(refresh_fails=True, write_mode="rollback"), PRESS, check("rollback error, refresh failed"),
             REFRESH.set(), CHECK_AGAIN, click("original"), PRESS, check("recovered"),
             REFRESH.set())

    def test_r1_success_then_refresh_failure(self):
        start, s = self.state("start"), self.state("success, refresh failed")
        # 書き込みは成功している（設定は変わった）が、確かめられないので B だけを出す
        self.assertNotEqual(s["settings"], start["settings"])
        self.assertEqual(s["toasts"], start["toasts"] + [MSG_B])
        self.assertIs(s["banner"], False)
        # 古い「使用中」は残さず unknown にする（根拠なく custom にもしない）
        self.assertEqual(s["current"], "unknown")
        self.assertIs(s["unknown"], True)
        self.assertNoDetailOnScreen(s)
        self.assertIn(SECRET_DETAIL, s["log"])

    def test_r2_write_error_then_refresh_failure(self):
        before, s = self.state("success, refresh failed"), self.state("write error, refresh failed")
        self.assertEqual(s["toasts"], before["toasts"] + ["Failed to write dock-position", MSG_B])
        self.assertIs(s["banner"], False)
        self.assertEqual(s["current"], "unknown")
        self.assertIs(s["unknown"], True)
        self.assertNoDetailOnScreen(s)

    def test_r3_rollback_error_and_refresh_failure_keeps_banner(self):
        before, s = self.state("write error, refresh failed"), self.state("rollback error, refresh failed")
        self.assertIs(s["banner"], True)
        self.assertIs(s["unknown"], True)
        self.assertEqual(s["toasts"], before["toasts"] + [MSG_B])
        self.assertNoDetailOnScreen(s)

    def test_r4_recovers_after_faults_cleared(self):
        s = self.state("recovered")
        self.assertIs(s["banner"], False)
        self.assertIs(s["unknown"], False)
        self.assertEqual(s["toasts"][-1], "Applied oYo Original.")
        self.assertEqual(s["current"], "original")


#----------------------------------------------------------------------------------------------------------------
# 現在のレイアウトを確認できない（unknown）とき（Startup Exception Safety）
#----------------------------------------------------------------------------------------------------------------
MSG_UNKNOWN = ns["MSG_LAYOUT_UNKNOWN"]
MSG_STILL = ns["MSG_LAYOUT_STILL_UNKNOWN"]


class ReaderControl:
    """
    アプリに渡す設定の読み取り処理（memory backend の実際の値を読む）。ステップで失敗のさせ方を切り替える。
      mode None   : そのまま読む
      mode "raise": 例外を出す
      mode "shell": shell の enabled-extensions が読めなかった状態を返す
      mode "custom": dock-position を RIGHT として返す（読めた値が一致しない、正常な custom）
    """

    def __init__(self, mode=None):
        self.start_mode = mode
        self.mode = mode

    def read(self):
        if self.mode == "raise":
            raise RuntimeError(SECRET_DETAIL)
        state = ns["read_current_state"]()
        if self.mode == "shell":
            state["shell"]["keys"]["enabled-extensions"]["value"] = None
        elif self.mode == "custom":
            state["dash-to-dock"]["keys"]["dock-position"]["value"] = "RIGHT"
        return state

    def set(self, mode):
        return call(lambda _app: setattr(self, "mode", mode))


def unknown_view(app):
    top_bars = app.rollback_banner.get_parent()
    return {
        "current": app.current_layout,
        "selected": app.selected_layout,
        "badges": [k for k, badge in app.current_badges.items() if badge.get_visible()],
        "active": [k for k, card in app.cards.items() if card.get_active()],
        "notice": app.custom_notice.get_visible(),
        "apply": app.apply_button.get_sensitive(),
        "unknown": app.unknown_banner.get_revealed(),
        "unknown_title": app.unknown_banner.get_title(),
        "unknown_button": app.unknown_banner.get_button_label(),
        "unknown_markup": app.unknown_banner.get_use_markup(),
        "rollback": app.rollback_banner.get_revealed(),
        # 2 つの警告が同じ並びにあり、rollback の警告のすぐ下に unknown の警告がある
        "banner_order": (app.unknown_banner.get_parent() is top_bars
                         and app.rollback_banner.get_next_sibling() is app.unknown_banner),
        "toasts": list(app.test_toasts),
        "log": app.test_log.getvalue(),
        "settings": settings_snapshot(),
    }


class UnknownScenarioTestCase(GuiScenarioTestCase):
    READER = None
    INJECTOR = None

    @classmethod
    def setUpClass(cls):
        cls.display = display_available()
        if cls.display:
            cls.READER.mode = cls.READER.start_mode
            if cls.INJECTOR is not None:
                cls.INJECTOR.install()
            try:
                cls.results, cls.failure = run_scenario(cls.STEPS, view_fn=unknown_view, state_reader=cls.READER.read)
            finally:
                if cls.INJECTOR is not None:
                    cls.INJECTOR.uninstall()

    def state(self, label):
        self.assertIsNone(self.failure)
        self.assertIn(label, self.results)
        return self.results[label][0]

    def assertUnknownShown(self, s):
        self.assertEqual(s["current"], "unknown")
        self.assertIs(s["unknown"], True)
        self.assertEqual(s["badges"], [])
        self.assertIs(s["notice"], False)
        self.assertIs(s["apply"], False)

    def assertNoDetailOnScreen(self, s):
        for toast in s["toasts"]:
            self.assertNotIn(SECRET_DETAIL, toast)
            self.assertNotIn("RuntimeError", toast)


NORMAL_READER = ReaderControl()


class GuiNormalLayoutsNoUnknownTest(UnknownScenarioTestCase):
    """1: 正常な 4 レイアウトでは、従来どおり「使用中」を出し、unknown の警告は出さない"""

    READER = NORMAL_READER
    STEPS = (check("original"),
             click("windows10"), PRESS, check("windows10"),
             click("windows11"), PRESS, check("windows11"),
             click("macos"), PRESS, check("macos"),
             click("original"), PRESS, check("original again"))

    def test_k1_normal_layouts(self):
        for label, layout_id in (("original", "original"), ("windows10", "windows10"), ("windows11", "windows11"),
                                 ("macos", "macos"), ("original again", "original")):
            with self.subTest(label):
                s = self.state(label)
                self.assertEqual((s["current"], s["badges"], s["active"]), (layout_id, [layout_id], [layout_id]))
                self.assertIs(s["unknown"], False)
                self.assertIs(s["notice"], False)
                self.assertIs(s["apply"], False)
        self.assertEqual(self.state("original again")["toasts"],
                         ["Applied Windows 10.", "Applied Windows 11.", "Applied macOS.", "Applied oYo Original."])

    def test_k2_unknown_banner_widget(self):
        s = self.state("original")
        self.assertEqual(s["unknown_title"], MSG_UNKNOWN)
        self.assertEqual(s["unknown_button"], "Check Again")
        self.assertIs(s["unknown_markup"], False)
        self.assertIs(s["banner_order"], True)


CUSTOM_READER = ReaderControl("custom")


class GuiNormalCustomTest(UnknownScenarioTestCase):
    """2: 読めた値がどれにも一致しない（正常な custom）は、従来どおり Custom の案内を出し、Apply できる"""

    READER = CUSTOM_READER
    STEPS = (check("start"), click("original"), check("original selected"), CUSTOM_READER.set(None))

    def test_k3_custom_is_not_unknown(self):
        s = self.state("start")
        self.assertEqual(s["current"], "custom")
        self.assertIs(s["notice"], True)
        self.assertIs(s["unknown"], False)
        self.assertEqual((s["badges"], s["active"], s["apply"]), ([], [], False))
        s = self.state("original selected")
        self.assertIs(s["apply"], True)
        self.assertIs(s["unknown"], False)


STARTUP_READER = ReaderControl("raise")


class GuiStartupUnknownTest(UnknownScenarioTestCase):
    """3〜8: 起動時に読み取れない → Apply 禁止 → 再確認（失敗・失敗・成功）→ 選択を保持して回復"""

    READER = STARTUP_READER
    STEPS = (check("start"),
             click("macos"), check("card selected"),
             PRESS, check("press refused"),
             call(lambda a: a.on_apply_clicked(a.apply_button)), check("direct call refused"),
             CHECK_AGAIN, check("check again failed"),
             STARTUP_READER.set("shell"), CHECK_AGAIN, check("check again failed (shell)"),
             STARTUP_READER.set(None), CHECK_AGAIN, check("recovered"),
             PRESS, check("applied after recovery"))

    def test_k4_startup_unknown_shows_banner(self):
        s = self.state("start")
        self.assertUnknownShown(s)
        self.assertEqual((s["selected"], s["active"]), (None, []))
        self.assertIs(s["rollback"], False)
        self.assertEqual(s["toasts"], [])
        # 詳細はログにだけ残す
        self.assertIn(SECRET_DETAIL, s["log"])
        self.assertIn("Traceback", s["log"])

    def test_k5_card_selection_keeps_apply_disabled(self):
        s = self.state("card selected")
        self.assertUnknownShown(s)
        self.assertEqual((s["selected"], s["active"]), ("macos", ["macos"]))

    def test_k6_apply_event_does_not_write(self):
        start = self.state("start")
        for label in ("press refused", "direct call refused"):
            with self.subTest(label):
                s = self.state(label)
                self.assertUnknownShown(s)
                self.assertEqual(s["settings"], start["settings"])
                self.assertEqual(s["toasts"], [])
                self.assertEqual(s["rollback"], False)
        self.assertIn("refused because the current layout is unknown", self.state("direct call refused")["log"])

    def test_k7_check_again_failure_keeps_unknown(self):
        start = self.state("start")
        s = self.state("check again failed")
        self.assertUnknownShown(s)
        self.assertEqual(s["toasts"], [MSG_STILL])
        self.assertEqual(s["settings"], start["settings"])
        self.assertNoDetailOnScreen(s)
        s = self.state("check again failed (shell)")
        self.assertUnknownShown(s)
        self.assertEqual(s["toasts"], [MSG_STILL, MSG_STILL])
        self.assertEqual(s["settings"], start["settings"])
        self.assertIn("shell enabled-extensions could not be read", s["log"])

    def test_k8_check_again_success_recovers_and_keeps_selection(self):
        s = self.state("recovered")
        self.assertEqual(s["current"], "original")
        self.assertEqual(s["badges"], ["original"])
        self.assertIs(s["unknown"], False)
        self.assertIs(s["notice"], False)
        # 選んでいた macOS はそのまま。今と違うので Apply できる。成功したときはトーストを出さない
        self.assertEqual((s["selected"], s["active"]), ("macos", ["macos"]))
        self.assertIs(s["apply"], True)
        self.assertEqual(s["toasts"], [MSG_STILL, MSG_STILL])
        s = self.state("applied after recovery")
        self.assertEqual((s["current"], s["badges"], s["apply"]), ("macos", ["macos"], False))
        self.assertEqual(s["toasts"][-1], "Applied macOS.")


AUTOSELECT_READER = ReaderControl("raise")


class GuiStartupUnknownAutoSelectTest(UnknownScenarioTestCase):
    """8: カードを選んでいなければ、再確認で確認できたときに使用中のカードを選ぶ"""

    READER = AUTOSELECT_READER
    STEPS = (check("start"), AUTOSELECT_READER.set(None), CHECK_AGAIN, check("recovered"))

    def test_k9_unselected_card_is_selected_on_recovery(self):
        self.assertEqual(self.state("start")["active"], [])
        s = self.state("recovered")
        self.assertEqual((s["current"], s["selected"], s["active"], s["badges"]),
                         ("original", "original", ["original"], ["original"]))
        self.assertIs(s["unknown"], False)
        self.assertIs(s["apply"], False)
        self.assertEqual(s["toasts"], [])


BOTH_READER = ReaderControl()
BOTH_INJECTOR = FailureInjector()


class GuiUnknownWithRollbackBannerTest(UnknownScenarioTestCase):
    """
    9〜13: Apply の後の読み直しで確認できない（読み取りの失敗）→ unknown。
    rollback の警告とは独立に出し入れし、再確認でも rollback の警告は消さない
    """

    READER = BOTH_READER
    INJECTOR = BOTH_INJECTOR
    STEPS = (check("start"),
             # 11: Apply 成功後の読み直しで確認できない
             BOTH_READER.set("raise"), click("windows10"), PRESS, check("success, unknown"),
             BOTH_READER.set(None), CHECK_AGAIN, check("checked 1"),
             # 12: ApplyWriteError 後の読み直しで確認できない
             BOTH_INJECTOR.mode_step("write"), BOTH_READER.set("raise"), click("macos"), PRESS,
             check("write error, unknown"),
             BOTH_INJECTOR.mode_step(None), BOTH_READER.set(None), CHECK_AGAIN, check("checked 2"),
             # 13: rollback の失敗と読み直しの失敗が重なる（Original から macOS）
             click("original"), PRESS, check("original"),
             BOTH_INJECTOR.mode_step("rollback"), BOTH_READER.set("raise"), click("macos"), PRESS,
             check("both banners"),
             BOTH_INJECTOR.mode_step(None), click("original"), check("card selected while unknown"),
             CHECK_AGAIN, check("still unknown, rollback kept"),
             # 10: 再確認で確認できても、rollback の警告は残る
             BOTH_READER.set(None), CHECK_AGAIN, check("checked, rollback kept"),
             # rollback の警告を閉じても unknown には影響しない（逆も同じ）
             BOTH_INJECTOR.mode_step("rollback"), BOTH_READER.set("raise"), click("macos"), PRESS,
             check("both banners again"),
             call(lambda a: a.rollback_banner.emit("button-clicked")), check("rollback dismissed while unknown"),
             BOTH_INJECTOR.mode_step(None), BOTH_READER.set(None), CHECK_AGAIN, click("original"), PRESS,
             check("applied"))

    def test_k10_success_then_unknown(self):
        start, s = self.state("start"), self.state("success, unknown")
        self.assertNotEqual(s["settings"], start["settings"])  # 書き込みは成功している
        self.assertUnknownShown(s)
        self.assertEqual(s["toasts"], [MSG_B])
        self.assertIs(s["rollback"], False)
        checked = self.state("checked 1")
        self.assertEqual((checked["current"], checked["badges"], checked["unknown"]), ("windows10", ["windows10"], False))

    def test_k11_write_error_then_unknown(self):
        before, s = self.state("checked 1"), self.state("write error, unknown")
        self.assertUnknownShown(s)
        self.assertEqual(s["toasts"], before["toasts"] + ["Failed to write dock-position", MSG_B])
        self.assertIs(s["rollback"], False)
        self.assertEqual(s["settings"], before["settings"])  # 書き込みの失敗は元に戻っている

    def test_k12_rollback_failure_and_unknown_show_both(self):
        before, s = self.state("original"), self.state("both banners")
        self.assertEqual(before["current"], "original")
        self.assertUnknownShown(s)
        self.assertIs(s["rollback"], True)
        self.assertIs(s["banner_order"], True)
        self.assertEqual(s["toasts"], before["toasts"] + [MSG_B])
        # unknown のあいだはカードを選んでも Apply できず、どちらの警告も消えない
        s = self.state("card selected while unknown")
        self.assertUnknownShown(s)
        self.assertIs(s["rollback"], True)
        s = self.state("still unknown, rollback kept")
        self.assertUnknownShown(s)
        self.assertIs(s["rollback"], True)
        self.assertEqual(s["toasts"][-1], MSG_STILL)

    def test_k13_check_again_keeps_rollback_banner(self):
        before, s = self.state("still unknown, rollback kept"), self.state("checked, rollback kept")
        self.assertIs(s["unknown"], False)
        self.assertIs(s["rollback"], True)
        self.assertEqual(s["current"], "custom")  # 一部が戻らなかったので custom（読めたうえでの判定）
        self.assertIs(s["notice"], True)
        self.assertEqual((s["selected"], s["apply"]), ("original", True))
        self.assertEqual(s["toasts"], before["toasts"])

    def test_k14_banners_are_independent(self):
        s = self.state("both banners again")
        self.assertIs(s["rollback"], True)
        self.assertIs(s["unknown"], True)
        s = self.state("rollback dismissed while unknown")
        self.assertIs(s["rollback"], False)
        self.assertUnknownShown(s)
        s = self.state("applied")
        self.assertEqual((s["current"], s["rollback"], s["unknown"]), ("original", False, False))
        self.assertEqual(s["toasts"][-1], "Applied oYo Original.")


if __name__ == "__main__":
    unittest.main()
