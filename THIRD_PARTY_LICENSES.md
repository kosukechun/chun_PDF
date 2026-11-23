# 同梱コンポーネント

chun PDF のソースとビルド手順は [プロジェクトのリポジトリ](https://github.com/kosukechun/chun_PDF) にあります。配布物内の `licenses/`、`LICENSE`、`_internal/assets/tessdata/LICENSE` も参照してください。

|コンポーネント|主なライセンス|対応するソース・用途|
|---|---|---|
|PyMuPDF 1.26.7 とその MuPDF ランタイム|GNU AGPL v3|[PyMuPDF](https://github.com/pymupdf/PyMuPDF/tree/1.26.7)、[MuPDF](https://github.com/ArtifexSoftware/mupdf)。PDF描画・編集・圧縮・OCR連携|
|Tesseract / Leptonica|Apache-2.0 / BSD系|MuPDFに組み込まれるOCR実装。[Tesseract](https://github.com/tesseract-ocr/tesseract)、[Leptonica](https://github.com/DanBloomberg/leptonica)|
|tessdata_fast 4.1.0|Apache-2.0|[言語モデル](https://github.com/tesseract-ocr/tessdata_fast/tree/4.1.0)。eng、jpn、jpn_vertを同梱|
|CPython / Tcl/Tk|PSF / Tcl/Tk license|[Python](https://www.python.org/downloads/source/)、[Tcl/Tk](https://www.tcl-lang.org/software/tcltk/)|
|Pillow|MIT-CMU|[ソース](https://github.com/python-pillow/Pillow/tree/11.2.1)。画像入出力。ホイールのネイティブライブラリの通知も同梱|
|tkinterdnd2 / tkdnd|MIT / Tcl/Tk系|[ソース](https://github.com/pmgagne/tkinterdnd2)。ファイルドロップ|
|pywin32|PSF系、各ファイルの著作権表示を参照|[ソース](https://github.com/mhammond/pywin32)。トレイ、単一起動、画像クリップボード|
|PyInstaller|GPL v2以降、ブートローダー例外あり|[ソースと例外条項](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt)|
|Inno Setup|Inno Setup License|[ソース](https://github.com/jrsoftware/issrc)。セットアップ作成|

アプリの利用に有料サービスやライセンスキーは不要です。ソフトウェアを再配布する場合には、同梱の著作権表示・ライセンスを保持し、AGPL に従って対応するソースを提供してください。

