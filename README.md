# oyo-ui-changer

`oyo-ui-changer` は、**GNOME の外観（UI）プリセットをワンクリックで適用**するためのユーティリティ（Debian パッケージ）です。  
`dconf` を用いて各種 GNOME Shell 拡張機能の設定・有効化を行い、**oYo Original / Windows Style / Mac Style** の 3 プロファイルを切り替えます。  
UI 選択には `zenity` を使用した簡易 GUI を提供します。

---

## リポジトリ構成

- `debian/` : Debian パッケージのメタデータ  
- `usr/bin/oyo-ui-changer` : 実行スクリプト本体  
- `.github/workflows/release.yml` : CI/CD ワークフロー定義  

---

## 機能（プロファイル別の適用内容）

UI 適用時は、一旦 **拡張機能を無効化** → **設定反映** → **拡張機能を再有効化** します。  
（`dconf write /org/gnome/shell/disable-user-extensions true/false`）

### 1) oYo Original Style
- **Dash to Dock**
  - `custom-theme-shrink=true`, `dock-fixed=true`, `dash-max-icon-size=32`
  - `extend-height=true`, `dock-position='LEFT'`
  - `running-indicator-style='DOTS'`, `transparency-mode='DYNAMIC'`
  - `show-apps-at-top=false`, `click-action='minimize'`
- **ウィンドウボタン配置**
  - `'appmenu:minimize,maximize,close'`
- **有効化する拡張機能**
  - `['dash-to-dock@micxgx.gmail.com','add-to-desktop@tommimon.github.com','ding@rastersoft.com','kimpanel@kde.org']`

### 2) Windows UI Style
- **Arc Menu**
  - `menu-layout='Windows'`, `position-in-panel='Left'`
- **Dash to Panel**
  - `panel-positions='{"0":"BOTTOM"}'`, `panel-sizes='{"0":36}'`
  - `panel-element-positions` を JSON で詳細配置（タスクバー有効／左寄せ 等）
- **ウィンドウボタン配置**
  - `'appmenu:minimize,maximize,close'`
- **有効化する拡張機能**
  - `['arcmenu@arcmenu.com','dash-to-panel@jderose9.github.com','add-to-desktop@tommimon.github.com','ding@rastersoft.com','kimpanel@kde.org']`

### 3) Mac UI Style
- **Arc Menu**
  - `menu-layout='Brisk'`, `position-in-panel='Left'`
- **Dash to Dock**
  - `custom-theme-shrink=true`, `dock-fixed=false`, `dash-max-icon-size=38`
  - `extend-height=false`, `dock-position='BOTTOM'`
  - `running-indicator-style='DOTS'`, `transparency-mode='DYNAMIC'`
  - `show-apps-at-top=true`, `click-action='minimize'`
- **Dash to Panel**
  - `panel-positions='{"0":"TOP"}'`, `panel-sizes='{"0":32}'`
  - `panel-element-positions` を JSON で詳細配置（トップパネル／タスクバー非表示 等）
- **ウィンドウボタン配置**
  - `'close,minimize,maximize:appmenu'`
- **有効化する拡張機能**
  - `['arcmenu@arcmenu.com','dash-to-panel@jderose9.github.com','add-to-desktop@tommimon.github.com','ding@rastersoft.com','kimpanel@kde.org','dash-to-dock@micxgx.gmail.com']`

---

## 依存関係

- ランタイム: `bash`, `dconf`, `zenity`
- GNOME Shell 拡張:
  - `arcmenu@arcmenu.com`
  - `dash-to-panel@jderose9.github.com`
  - `dash-to-dock@micxgx.gmail.com`
  - `add-to-desktop@tommimon.github.com`
  - `ding@rastersoft.com`
  - `kimpanel@kde.org`

> これらの拡張が未インストールの場合、設定適用に失敗します。パッケージ依存またはインストールドキュメントで担保してください。

---

## 使い方

```bash
# GUI で UI を選択して適用
oyo-ui-changer
```

- ダイアログで UI を選択 → OK で適用  
- 成功メッセージを `zenity --info` で表示  

---

## CI/CD の仕組み

本リポジトリは GitHub Actions で `.deb` を自動ビルド・リリース。  
次に [`apt-repo-infra`](https://github.com/openyellowos/apt-repo-infra) を **手動で Run workflow** し、APT リポジトリに反映します。

### フロー

1. タグを push  
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
2. Actions が `.deb` をビルドし Release に添付  
3. `apt-repo-infra` の **Run workflow** を実行（手動）  
4. `deb.openyellowos.org` に公開

### 図解（Mermaid）

```mermaid
flowchart LR
    dev["開発者 (tag vX.Y.Z)"] --> actions["GitHub Actions (oyo-ui-changer)"]
    actions --> release["GitHub Release（成果物添付）"]
    release -->|Run workflow 手動| infra["apt-repo-infra（Run workflow 実行）"]
    infra --> repo["deb.openyellowos.org（APT リポジトリに公開）"]
```


---

## ローカルビルド

```bash
sudo apt-get install devscripts debhelper
debuild -us -uc
ls ../*.deb
```

---

## バージョニング / 環境

- Semantic Versioning（`vX.Y.Z`）  
- **staging / production** を想定（現状は主に production）

---

## ライセンス

MIT License  
© open.Yellow.os Project Team

---

## メンテナンス

- プロジェクト: [open.Yellow.os](https://openyellowos.org)  
- GitHub: [openyellowos/oyo-ui-changer](https://github.com/openyellowos/oyo-ui-changer)
