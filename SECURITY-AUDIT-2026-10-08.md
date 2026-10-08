# セキュリティレビュー — 2026-10-08

対象: index.html、security.js、external-services.js、vendor の依存ライブラリ、tests、README.md、SECURITY.md、ワークスペース設定。現在の作業ツリーに対するソースレビュー、Edge headless / Playwright による追加検証、依存の公式セキュリティ情報確認を実施した。親フォルダの個人制作物、Git 全履歴、公開先サーバー設定は対象外。

既存テストは `python -m unittest discover -s tests` で **84件成功（66.542秒）**。追加検証は独立ブラウザーで HTTP/HTTPS を遮断して実施した。以下の4件は既存テストでは検出されない。本体コードは変更していない。

## 1. 中: 読み込み設定からのCSS再生成で検査を迂回

- 箇所: `security.js:126` の sanitizeArticleSettings、`index.html:6749` の textStyle、`index.html:8242` の cssText 代入、`index.html:8460` の保存済み設定の再利用。
- 条件: 第三者のJSONに含まれる documentBlockDefaults.heading を読み込み、その後に見出しを追加する。
- 原因: `<` を含まない文字列は設定の検査を通過する。headingFont / headingWeight がCSS宣言文字列へ直接連結されるため、セミコロンで別の宣言を追加できる。
- 検証: 次の設定で読み込み後に `insertDocumentBlock('heading')` を実行した。

```json
{
  "saveType": "full",
  "settings": {
    "documentBlockDefaults": {
      "heading": {
        "headingFont": "inherit;background-image:url(https://audit.invalid/css);position:fixed;inset:0;z-index:999999"
      },
      "body": { "includeCard": false }
    }
  },
  "articleHtml": "<p>test</p>"
}
```

実際の見出しに background-image、position:fixed、z-index が設定され、遮断用ルートで `https://audit.invalid/css` への要求を観測した。これは SECURITY.md の「CSS外部リソース参照・固定配置・z-indexを除去」という保証を迂回する。プレビューの contain:paint は残るため、エディター全体を覆えるとは判定していない。任意JavaScript実行や本文漏えいも未確認。

関連して `sanitizeArticleMarkup('<p style="--p:fixed;position:var(--p);inset:0">x</p>')` は position:var(--p) を残す。CSS文字列中の fixed 検出だけでは、変数経由の固定配置も防げない。

修正: フォント・太さ等に型と許可値の検査を導入し、cssText への連結をやめて style.fontFamily / style.fontWeight 等へ個別代入する。配置指定は値の許可リストにするか、記事から position と関連するCSS変数を除去する。設定の読み込み→パーツ追加までの回帰テストを追加する。

## 2. 中: 結合セルの展開数が無制限で、編集時にDoSが可能

- 箇所: `index.html:18093` の getTableCellGrid、`index.html:18221` の上下キー操作、`index.html:18390` / `18417` の行列削除。
- 条件: rowspan / colspan の大きな表をHTMLまたはJSONで読み込み、表内で上下キー等を操作する。
- 原因: DOM要素数・ファイル容量の検査とは別に、rowSpan × colSpan の配列要素を同期的に生成する。実在する行数にも制限していない。
- 検証: `<table><tr><td rowspan="100" colspan="100">test</td></tr></table>` を通常の importArticleHtml 経由で読み込むと、属性が維持され、1セルから10,000個のグリッド要素が生成された。
- 影響: 少量の入力から大量のCPU・メモリー消費を誘発できる。大きな値や複数セルではタブ停止・未保存作業の喪失につながり得る。実際のブラウザークラッシュを起こす規模での実験はしていない。
- 修正: 検査時および展開直前に、行・列・論理セル総数の上限を設定する。rowspan は実在する行に切り詰める。可能なら疎な区間表現を使い、巨大な二次元配列を作らない。

## 3. 中: CSVの読み込みと列選択UIに容量・項目数上限がない

- 箇所: `index.html:17768` の parseCsv、`17812` 付近の readCsvFile、`17906` 付近の renderCsvColumnChoices、`18280` のファイル入力ハンドラー。
- 条件: 大容量CSVまたは大量の列を持つCSVを利用者が選択する。
- 原因: 全ファイルを arrayBuffer と文字列へ展開して全項目を解析する。その後、選択可能列数は6列でも、選択UIは全列についてDOMを生成する。最終的な取り込みの20行制限は、この前処理に効かない。
- 検証: 3,999バイトの1行2,000列CSVから、2,000個の列選択inputが生成された。容量チェックも列数の打ち切りもコード上存在しない。大規模クラッシュ実験は未実施。
- 影響: 第三者提供のCSVからタブの処理停止・メモリー圧迫を誘発できる。
- 修正: 読み込み前に file.size を制限し、パーサー内で行数・列数・総セル数・セル文字数を制限する。UI生成前にも列数を制限する。超過を処理開始前または解析途中で明示的に拒否する。

## 4. 低: 記事内のlabelが編集画面のボタンを作動させる

- 箇所: `security.js:68` 付近の許可要素・属性設定、`security.js:83` 付近のID衝突対策。
- 条件: 次のHTMLを読み込み、記事内の「続きを読む」をクリックする。

```html
<p>記事</p>
<label for="clearPreviewButton" contenteditable="false">続きを読む</label>
```

- 検証: importArticleHtml 後にも for 属性が残り、Playwright の実クリックでエディター本体の clearPreviewButton にclickが1回配送された。確認ダイアログは拒否した。
- 影響: 記事の表示内容に偽装してエディターの操作を誘発できる。クリアには既存の確認ダイアログがあるため、これだけで無確認削除できるという指摘ではない。ID重複の除去だけでは文書全体への参照を防げない。
- 修正: 記事内で不要なlabelとfor属性を禁止する。必要なら記事専用IDへ変換し、参照先が同じ記事内に存在することを検証する。formなど他のID参照属性も同様に扱う。

## 依存・残存リスク

- 同梱DOMPurifyは3.4.15。公式には3.4.16が公開され、IN_PLACE関連の2件が修正されている。現在のsecurity.jsは文字列入力・RETURN_DOMで、IN_PLACEや削除hookを使用しないため、今回の2件を実証済みXSSとして数えていない。更新は推奨する。
  - https://github.com/cure53/DOMPurify/releases/tag/3.4.16
  - https://github.com/cure53/DOMPurify/security/advisories/GHSA-p98j-92pf-mc4p
  - https://github.com/cure53/DOMPurify/security/advisories/GHSA-6688-9rhm-gjv2
- markedの同梱バージョンは18.0.7。公式advisory一覧も確認したが、本レビューでこの版に対する実証済みの追加問題は見つけていない。完全な既知脆弱性不在の保証ではない。
  - https://github.com/markedjs/marked/security/advisories
- `index.html:16135` ではXのwidgets.jsを編集ページと同じ権限で動的に実行する。提供元のスクリプトは記事DOMやlocalStorageへアクセスできる設計であり、SECURITY.mdにも記載済み。攻撃を実証したものではないが、隔離iframe化を検討する価値がある。
- 外部画像・動画の自動通信は仕様として明記されているため、それ自体を新規脆弱性として計上していない。
- 代表的な秘密鍵・APIトークン形式の現在ツリー検索では一致なし。すべての秘密情報形式・Git履歴を保証する検査ではない。

今回確認した範囲では任意JavaScript実行・任意ファイル読み取りは実証されなかった。ただし既存テスト成功は上記のUI干渉・CSS検査迂回・処理量制限の保証にはならない。
