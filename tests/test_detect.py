"""
detect_layout() の単体テスト（設定の読み書きはしない。偽の状態を渡して判定結果だけを見る）

旧スクラッチテスト uic-test5.py の 29 件を移したもの。入力と期待値は変えていない。
実行: python3 -m unittest discover -s tests -v
"""

import json
import unittest

from helpers import load_app  # gi より先に読み込む（memory backend の強制）

DOCK = "dash-to-dock@micxgx.gmail.com"
DTP = "dash-to-panel@jderose9.github.com"
ARC = "arcmenu@arcmenu.com"

J = json.dumps


def el(pos, visible=True):
    """panel-element-positions の 1 モニター分（taskbar の位置と表示だけを変える）"""
    return [{"element": "showAppsButton", "visible": False, "position": "stackedTL"},
            {"element": "taskbar", "visible": visible, "position": pos},
            {"element": "dateMenu", "visible": True, "position": "stackedBR"}]


def mk(enabled, dock_pos="LEFT", positions="{}", elements="{}", disabled=(), disable_user=False,
       installed=("dock", "panel", "arc")):
    """read_current_state() と同じ形の偽の状態を作る"""
    def k(**kv):
        return {key: {"value": v, "raw": None} for key, v in kv.items()}
    return {
        "shell": {"uuid": None, "installed": None,
                  "keys": k(**{"enabled-extensions": list(enabled), "disabled-extensions": list(disabled),
                               "disable-user-extensions": disable_user})},
        "dash-to-dock": {"uuid": DOCK, "installed": ["/x"] if "dock" in installed else [],
                         "keys": k(**{"dock-position": dock_pos})},
        "dash-to-panel": {"uuid": DTP, "installed": ["/x"] if "panel" in installed else [],
                          "keys": k(**{"panel-positions": positions, "panel-element-positions": elements})},
        "arcmenu": {"uuid": ARC, "installed": ["/x"] if "arc" in installed else [],
                    "keys": k(**{"menu-layout": "arcmenu"})},
    }


def none_value(state, name, key):
    state[name]["keys"][key]["value"] = None
    return state


def without(state, name):
    del state[name]
    return state


# (旧テストでの名前, 状態, 期待値)。順番も旧テストと同じ
CASES = [
    ("original (install default)", mk([DOCK, "ding@rastersoft.com", "kimpanel@kde.org"]), "original"),
    ("original + arcmenu enabled", mk([DOCK, ARC]), "original"),
    ("original, panel not installed", mk([DOCK, DTP], installed=("dock",)), "original"),
    ("windows10 explicit", mk([DTP, ARC], positions=J({"0": "BOTTOM"}), elements=J({"0": el("stackedTL")})), "windows10"),
    ("windows10 empty dicts (dtp defaults)", mk([DTP]), "windows10"),
    ("windows11 centerMonitor", mk([DTP, ARC], positions=J({"0": "BOTTOM"}), elements=J({"0": el("centerMonitor")})), "windows11"),
    ("windows11 centered", mk([DTP], positions=J({"0": "BOTTOM"}), elements=J({"0": el("centered")})), "windows11"),
    ("macos", mk([DTP, DOCK, ARC], dock_pos="BOTTOM", positions=J({"0": "TOP"})), "macos"),
    ("multi same (win10, 2 monitors)", mk([DTP], positions=J({"A-1": "BOTTOM", "B-2": "BOTTOM"}),
                                          elements=J({"A-1": el("stackedTL"), "B-2": el("stackedTL")})), "windows10"),
    ("multi same (macos, 2 monitors)", mk([DTP, DOCK], dock_pos="BOTTOM", positions=J({"A-1": "TOP", "B-2": "TOP"})), "macos"),
    ("CUSTOM multi mixed positions", mk([DTP], positions=J({"A-1": "BOTTOM", "B-2": "TOP"})), "custom"),
    ("CUSTOM multi mixed taskbar", mk([DTP], positions=J({"0": "BOTTOM"}),
                                      elements=J({"A": el("stackedTL"), "B": el("centerMonitor")})), "custom"),
    ("CUSTOM windows taskbar hidden", mk([DTP], positions=J({"0": "BOTTOM"}), elements=J({"0": el("stackedTL", visible=False)})), "custom"),
    ("CUSTOM windows taskbar stackedBR", mk([DTP], positions=J({"0": "BOTTOM"}), elements=J({"0": el("stackedBR")})), "custom"),
    ("CUSTOM windows panel TOP", mk([DTP], positions=J({"0": "TOP"})), "custom"),
    ("CUSTOM panel LEFT", mk([DTP], positions=J({"0": "LEFT"})), "custom"),
    ("CUSTOM dock RIGHT, panel off", mk([DOCK], dock_pos="RIGHT"), "custom"),
    ("CUSTOM mac with dock LEFT", mk([DTP, DOCK], dock_pos="LEFT", positions=J({"0": "TOP"})), "custom"),
    ("CUSTOM mac with panel BOTTOM", mk([DTP, DOCK], dock_pos="BOTTOM"), "custom"),
    ("CUSTOM both disabled (plain GNOME)", mk(["ding@rastersoft.com"]), "custom"),
    ("CUSTOM dock in disabled-extensions", mk([DOCK], disabled=[DOCK]), "custom"),
    ("CUSTOM disable-user-extensions true", mk([DOCK], disable_user=True), "custom"),
    ("CUSTOM dock enabled but not installed", mk([DOCK], installed=("panel", "arc")), "custom"),
    ("CUSTOM taskbar element missing", mk([DTP], positions=J({"0": "BOTTOM"}),
                                          elements=J({"0": [{"element": "dateMenu", "position": "stackedBR"}]})), "custom"),
    ("CUSTOM broken JSON", mk([DTP], positions="{not json"), "custom"),
    # None を含む状態
    ("NONE enabled-extensions", none_value(mk([DOCK]), "shell", "enabled-extensions"), "custom"),
    ("NONE dock-position", none_value(mk([DOCK]), "dash-to-dock", "dock-position"), "custom"),
    ("NONE panel-positions (windows)", none_value(mk([DTP]), "dash-to-panel", "panel-positions"), "custom"),
    ("NONE missing dash-to-panel entry", without(mk([DOCK]), "dash-to-panel"), "custom"),
]


class DetectLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 安全に読み込めなければ UnsafeTestEnvironment で止まり、テストは実行されない
        cls.detect = staticmethod(load_app()["detect_layout"])

    def test_case_count(self):
        self.assertEqual(len(CASES), 29)


def _make_test(state, expected):
    def test(self):
        self.assertEqual(self.detect(state), expected)
    return test


# 1 件ずつ別のテストとして数えられるようにする（test_01_... 〜 test_29_...）
for _i, (_name, _state, _expected) in enumerate(CASES, 1):
    _test = _make_test(_state, _expected)
    _test.__doc__ = _name
    setattr(DetectLayoutTest, f"test_{_i:02d}_{_expected}", _test)


if __name__ == "__main__":
    unittest.main()
