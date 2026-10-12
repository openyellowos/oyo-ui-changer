"""
日本語翻訳（po/ja.po）のテスト

  - msgfmt --check で翻訳ファイルを一時ディレクトリにコンパイルできる（リポジトリには .mo を作らない）
  - POT の 21 件すべてに日本語訳があり、空訳・fuzzy がない
  - 差し込み（{name} など）が英語原文と一致し、値を差し込める
  - gettext で読み込むと日本語訳が得られ、未翻訳は英語のまま
  - アプリの表示文言は、そのテストの間だけ ns["_translation"] を差し替えたときだけ日本語になる
    （helpers は英語に固定しているので、ほかのテストには影響しない）
  - POT がソースと一致している（XGETTEXT_COMMAND で作り直して比べる）
  - rollback が不完全なときの警告（Banner）が、GUI で日本語の本文と「閉じる」ボタンで表示される
msgfmt がなければ skip する（xgettext・画面がなければ、そのテストだけ skip）。
実行: python3 -m unittest discover -s tests -v
"""

import ast
import gettext
import os
import shutil
import string
import subprocess
import tempfile
import unittest

import helpers
from helpers import REPO_DIR, load_app

DOMAIN = "oyo-ui-changer"
POT = os.path.join(REPO_DIR, "po", "oyo-ui-changer.pot")
JA_PO = os.path.join(REPO_DIR, "po", "ja.po")
EXPECTED_COUNT = 21
# POT を作るコマンド（po/oyo-ui-changer.pot はこのコマンドで作り直す）
XGETTEXT_COMMAND = ["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=_", "--keyword=N_",
                    "--add-location=file", "--package-name=oyo-ui-changer"]
APP_SOURCE = os.path.join(REPO_DIR, "src", "oyo-ui-changer.py")
BANNER_JA = "レイアウトの適用に失敗し、一部の設定を元に戻せませんでした。デスクトップの設定が変更されたままの可能性があります。レイアウトを選び直して、再度適用すると改善する場合があります。"
UNEXPECTED_JA = "予期しないエラーのため、レイアウトを適用できませんでした。"
CHECK_FAILED_JA = "現在のレイアウトを確認できませんでした。表示が実際のデスクトップと異なる可能性があります。"

# 確定した日本語の文言
CONFIRMED = {
    "Desktop Layout": "デスクトップのレイアウト",
    "Choose a desktop layout style.": "お好みのレイアウトを選択してください。",
    "Current": "使用中",
    "Apply": "適用",
    "Current desktop layout is customized.": "現在のレイアウトはカスタマイズされています。",
    "Applied {name}.": "{name} を適用しました。",
    "Could not confirm that {name} was applied.": "{name} が正しく適用されたことを確認できませんでした。",
    "{name} is not installed.": "{name} がインストールされていません。",
    "User extensions are disabled. Enable GNOME Shell extensions before applying this layout.":
        "GNOME Shell の拡張機能が無効になっています。レイアウトを適用するには、拡張機能を有効にしてください。",
    "The layout could not be applied, and some settings could not be restored. Your desktop may remain partly "
    "changed. Selecting a layout and applying it again may help.": BANNER_JA,
    "Dismiss": "閉じる",
    "The layout could not be applied because of an unexpected error.": UNEXPECTED_JA,
    "The current layout could not be checked. The display may not match your desktop.": CHECK_FAILED_JA,
}
# 訳文にもそのまま残すべき技術的な語
TECHNICAL_TERMS = ("GNOME Shell", "dash-to-panel")


def read_po(path):
    """PO / POT を読み、[{"msgid", "msgstr", "flags"}] を返す（見出し msgid "" は除く）"""
    entries, entry, field = [], None, None

    def finish():
        if entry is not None and entry["msgid"]:
            entries.append(entry)

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("#,"):
                finish()
                entry, field = {"msgid": "", "msgstr": "", "flags": set()}, None
                entry["flags"] |= {flag.strip() for flag in line[2:].split(",")}
            elif line.startswith(("msgid ", "msgstr ")):
                key, _sep, quoted = line.partition(" ")
                if key == "msgid" and (entry is None or field == "msgstr"):
                    finish()
                    entry = {"msgid": "", "msgstr": "", "flags": set()}
                field = key
                entry[field] += ast.literal_eval(quoted)
            elif line.startswith('"') and entry is not None and field:
                entry[field] += ast.literal_eval(line)
    finish()
    return entries


def placeholders(text):
    return {field for _literal, field, _spec, _conv in string.Formatter().parse(text) if field is not None}


def run_tool(args):
    """gettext の道具を固定の引数で起動する。helpers が外部コマンドを止めた後でも使えるよう、
    helpers が止める前に保持している起動手段を使う（dconf などアプリの経路には使わない）"""
    proc = helpers._real_popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate(timeout=30)
    return proc.returncode, out, err


@unittest.skipUnless(shutil.which("msgfmt"), "msgfmt (gettext) is not installed")
class JapaneseTranslationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.localedir = tempfile.mkdtemp(prefix="oyo-i18n-test-")
        cls.addClassCleanup(shutil.rmtree, cls.localedir)
        mo = os.path.join(cls.localedir, "ja", "LC_MESSAGES", DOMAIN + ".mo")
        os.makedirs(os.path.dirname(mo))
        cls.msgfmt = run_tool(["msgfmt", "--check", "-o", mo, JA_PO])
        cls.pot = read_po(POT)
        cls.po = read_po(JA_PO)
        cls.translations = {e["msgid"]: e["msgstr"] for e in cls.po}

    def japanese(self):
        return gettext.translation(DOMAIN, self.localedir, languages=["ja"])

    def test_01_msgfmt_check_passes(self):
        returncode, _out, err = self.msgfmt
        self.assertEqual(returncode, 0, err)

    def test_02_all_pot_messages_translated(self):
        pot_ids = [e["msgid"] for e in self.pot]
        self.assertEqual(len(pot_ids), EXPECTED_COUNT)
        self.assertEqual(set(self.translations), set(pot_ids))

    def test_03_no_empty_or_fuzzy_translations(self):
        for entry in self.po:
            with self.subTest(msgid=entry["msgid"]):
                self.assertTrue(entry["msgstr"].strip())
                self.assertNotIn("fuzzy", entry["flags"])

    def test_04_placeholders_match_english(self):
        pot_flags = {e["msgid"]: e["flags"] for e in self.pot}
        for msgid, msgstr in self.translations.items():
            with self.subTest(msgid=msgid):
                self.assertEqual(placeholders(msgstr), placeholders(msgid))
                self.assertEqual("python-brace-format" in pot_flags[msgid], bool(placeholders(msgid)))

    def test_05_values_can_be_inserted(self):
        for msgid, msgstr in self.translations.items():
            with self.subTest(msgid=msgid):
                values = {field: f"<{field}-value>" for field in placeholders(msgid)}
                text = msgstr.format(**values)
                for value in values.values():
                    self.assertIn(value, text)

    def test_06_confirmed_wording(self):
        for msgid, expected in CONFIRMED.items():
            with self.subTest(msgid=msgid):
                self.assertEqual(self.translations[msgid], expected)

    def test_07_technical_terms_kept(self):
        for msgid, msgstr in self.translations.items():
            for term in TECHNICAL_TERMS:
                if term in msgid:
                    with self.subTest(msgid=msgid, term=term):
                        self.assertIn(term, msgstr)

    def test_08_gettext_returns_japanese(self):
        translation = self.japanese()
        for msgid, msgstr in self.translations.items():
            with self.subTest(msgid=msgid):
                self.assertEqual(translation.gettext(msgid), msgstr)

    def test_09_untranslated_falls_back_to_english(self):
        self.assertEqual(self.japanese().gettext("Text that is not in the catalog"), "Text that is not in the catalog")
        other = gettext.translation(DOMAIN, self.localedir, languages=["fr"], fallback=True)
        self.assertIs(type(other), gettext.NullTranslations)
        self.assertEqual(other.gettext("Apply"), "Apply")

    def test_10_app_text_is_japanese_only_while_swapped(self):
        ns = load_app()
        english = ns["_translation"]
        self.assertIs(type(english), gettext.NullTranslations)
        self.addCleanup(ns.__setitem__, "_translation", english)

        ns["_translation"] = self.japanese()
        self.assertEqual(ns["_"]("Current"), "使用中")
        with self.assertRaises(ns["ApplyError"]) as caught:
            ns["plan_layout"]("custom")  # 設定を開く前に止まる（書き込みなし）
        self.assertEqual(str(caught.exception), "まだ実装されていません。")
        # GUI の例外通知の文言（アプリの定数を翻訳して得る）
        self.assertEqual(ns["_"](ns["MSG_UNEXPECTED_APPLY_ERROR"]), UNEXPECTED_JA)
        self.assertEqual(ns["_"](ns["MSG_LAYOUT_CHECK_FAILED"]), CHECK_FAILED_JA)

        ns["_translation"] = english
        self.assertEqual(ns["_"]("Current"), "Current")
        self.assertEqual(ns["_"](ns["MSG_UNEXPECTED_APPLY_ERROR"]), ns["MSG_UNEXPECTED_APPLY_ERROR"])

    @unittest.skipUnless(shutil.which("xgettext"), "xgettext (gettext) is not installed")
    def test_11_pot_matches_source(self):
        # ソースから POT を作り直し、翻訳対象（msgid とその印）が po/oyo-ui-changer.pot と一致することを確かめる
        fresh = os.path.join(self.localedir, "fresh.pot")
        returncode, _out, err = run_tool(XGETTEXT_COMMAND + ["--output=" + fresh, APP_SOURCE])
        self.assertEqual(returncode, 0, err)
        summarize = lambda entries: {e["msgid"]: sorted(e["flags"]) for e in entries}  # noqa: E731
        self.assertEqual(summarize(read_po(fresh)), summarize(self.pot))

    def test_12_japanese_banner_in_gui(self):
        import test_gui  # GUI の仕組みはこのテストだけで使う（画面がなければ skip）
        if not test_gui.display_available():
            self.skipTest("no display connection")
        gns, Gtk = test_gui.ns, test_gui.Gtk

        def texts(widget):
            found, child = [], widget.get_first_child()
            if isinstance(widget, (Gtk.Label, Gtk.Button)) and widget.get_label():
                found.append(widget.get_label())
            while child:
                found += texts(child)
                child = child.get_next_sibling()
            return found

        def banner_state(app):
            banner = app.rollback_banner
            return {"revealed": banner.get_revealed(), "title": banner.get_title(), "button": banner.get_button_label(),
                    "shown_texts": texts(banner), "apply": app.apply_button.get_label(), "toasts": list(app.test_toasts)}

        english = gns["_translation"]
        gns["_translation"] = self.japanese()
        injector = test_gui.FailureInjector()
        injector.install()
        try:
            results, failure = test_gui.run_scenario(
                (test_gui.check("start"), injector.mode_step("rollback"), test_gui.click("macos"), test_gui.PRESS,
                 test_gui.check("rollback failed"), injector.mode_step(None)),
                view_fn=banner_state)
        finally:
            injector.uninstall()
            gns["_translation"] = english

        self.assertIsNone(failure)
        start, after = results["start"][0], results["rollback failed"][0]
        self.assertEqual(start["apply"], "適用")
        self.assertIs(start["revealed"], False)
        self.assertIs(after["revealed"], True)
        self.assertEqual(after["title"], BANNER_JA)
        self.assertEqual(after["button"], "閉じる")
        self.assertIn(BANNER_JA, after["shown_texts"])
        self.assertIn("閉じる", after["shown_texts"])
        self.assertEqual(after["toasts"], start["toasts"])
        # 差し替えを戻したので、以後のアプリは英語
        self.assertEqual(gns["_"]("Dismiss"), "Dismiss")


if __name__ == "__main__":
    unittest.main()
