
# Debianのdebファイルを作成する手順

以下の手順で`deb`ファイルを作成できます。

---

## 1. ソースディレクトリを圧縮する

まず、ソースコードが格納されている`change-ui`ディレクトリを圧縮します。

```bash
tar czf change-ui_1.0.orig.tar.gz change-ui
```

---

## 2. ディレクトリに移動する

圧縮元の`change-ui`ディレクトリに移動します。

```bash
cd change-ui
```

---

## 3. `deb`ファイルをビルドする

次に、以下のコマンドを実行して`deb`ファイルを作成します。

```bash
debuild -uc -us
```

---

## 4. エラーについて

以下のようなエラーが出力される場合がありますが、問題ありません。

```
W: change-ui: initial-upload-closes-no-bugs [usr/share/doc/change-ui/changelog.Debian.gz:1]
W: change-ui source: no-debian-changes
```

---

## 5. 完成した`deb`ファイルを確認する

ビルドが成功すると、カレントディレクトリの1つ上に`deb`ファイルが生成されます。

```bash
cd ..
```

生成されたファイル：
```
change-ui_1.0-1_all.deb
```

これで、`deb`ファイルの作成は完了です！
