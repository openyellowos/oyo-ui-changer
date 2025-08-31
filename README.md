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

## クライアントPCからの取得方法

oYoのリポジトリからインストール可能です。

```bash
sudo apt update
sudo apt install oyo-ui-changer
```
---

## 使い方

```bash
# GUI で UI を選択して適用
oyo-ui-changer
```

- ダイアログで UI を選択 → OK で適用  
- 成功メッセージを `zenity --info` で表示  

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

> これらの拡張が未インストールの場合、設定適用に失敗します。
---

## 仕組みと設定方法（管理者向け）

- `dconf` コマンドを使って GNOME Shell の設定を切り替えています。  
- `dash-to-dock` などの GNOME 拡張機能を有効/無効にして UI を変更します。  

---

## CI/CD の仕組み（開発者向け）

`oyo-ui-changer` の開発では GitHub Actions を利用した CI/CD を導入しています。  
修正内容を push → tag を付与 → GitHub Actions で自動ビルド → `apt-repo-infra` でリポジトリ公開、という流れです。 

```mermaid
flowchart LR
    dev["開発者 (tag vX.Y.Z)"] --> actions["GitHub Actions (oyo-ui-changer)"]
    actions --> release["GitHub Release（成果物添付）"]
    release -->|Run workflow 手動| infra["apt-repo-infra（Run workflow 実行）"]
    infra --> repo["deb.openyellowos.org（APT リポジトリに公開）"]
``` 

### フロー概要

1. **ソースコード修正**
   ```bash
   git clone https://github.com/openyellowos/oyo-ui-changer.git
   cd oyo-ui-changer
   ```

2. **プログラム修正**
   - `bin/oyo-ui-changer` を編集する。  
   - 必要があれば README.md も修正する。  

3. **changelog 更新**
   ```bash
   debchange -i
   ```
   - changelog に修正内容を記入する。

4. **コミット & push**
   ```bash
   git add .
   git commit -m "修正内容を記述"
   git push origin main
   ```

5. **タグ付与**
   ```bash
   git tag v1.1-1
   git push origin v1.1-1
   ```

6. **GitHub Actions による自動ビルド**
   - タグ push を検知してワークフローが起動。  
   - `.deb` がビルドされ、GitHub Release に添付される。  

7. **APT リポジトリ公開**
   - `apt-repo-infra` の GitHub Actions を **手動で Run workflow** する。  
   - 実際の入力例：  
     - Source repo: `openyellowos/oyo-ui-changer`  
     - Release tag: `v1.1-1`  
     - Target environment: `production`  

   - 実行すると apt リポジトリに反映される。  
   - 利用者は以下で最新を取得可能：  
     ```bash
     sudo apt update
     sudo apt install oyo-ui-changer
     ```

---

### 注意事項

- **必ず changelog を更新すること**  
- **バージョン番号は changelog, git tag, GitHub Release を揃えること**  
- **依存関係変更時は debian/control を更新すること**
