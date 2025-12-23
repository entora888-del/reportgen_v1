import sys, traceback, tempfile, os, subprocess, html
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QObject, QThread, Signal
from PySide6.QtGui import QIcon, QGuiApplication, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextBrowser, QMessageBox, QGroupBox,
    QGridLayout, QCheckBox, QSizePolicy, QStyle, QScrollArea, QComboBox
)

from reportgen.parsers.liquefaction_pdf import summarize_liquefaction_pdf
from reportgen.wordgen.templater import (
    build_context_from_inputs,
    generate_docx_from_template,
)
from reportgen.utils.pathnorm import normalize_input_path
from reportgen.utils.template_locator import resolve_template_path  # ← 追加：テンプレ探索
from reportgen.nlftp.fetcher import (
    BookletFetchParams,
    BookletFetchResult,
    SOURCE_TEXT as BOOKLET_SOURCE_TEXT,
    fetch_booklets,
)
from reportgen.ai import AIOptions

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
DEFAULT_ICON = ASSETS_DIR / "reportgen_icon.png"


class DropLine(QLineEdit):
    """DnD/貼り付けされたパス文字列を正規化して受け取る行編集"""

    def __init__(self, patterns: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.patterns = patterns
        self.setAcceptDrops(True)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(48)
        self.setPlaceholderText("ファイルをドラッグ＆ドロップ（または参照）")

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or md.hasText():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            for u in md.urls():
                local = u.toLocalFile() or u.toString()
                p = normalize_input_path(local)
                if any(p.lower().endswith(ext) for ext in self.patterns):
                    self.setText(p)
                    break
            return
        if md.hasText():
            p = normalize_input_path(md.text())
            if any(p.lower().endswith(ext) for ext in self.patterns) or not self.patterns:
                self.setText(p)

    def insertFromMimeData(self, source):
        if source.hasText():
            self.setText(normalize_input_path(source.text()))
        else:
            super().insertFromMimeData(source)


class BookletFetchWorker(QObject):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, params: BookletFetchParams):
        super().__init__()
        self.params = params

    def run(self):
        try:
            result = fetch_booklets(self.params, progress_cb=self.progress.emit)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelFetchWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, api_key: str, base_choices: list[tuple[str, str]], max_models: int = 10):
        super().__init__()
        self.api_key = api_key
        self.base_choices = base_choices
        self.max_models = max(1, max_models)

    def run(self):
        try:
            from openai import OpenAI
        except ImportError:
            self.completed.emit(self.base_choices)
            return

        try:
            client = OpenAI(api_key=self.api_key)
            resp = client.models.list()
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        seen: set[str] = set()
        dynamic: list[tuple[str, str]] = []
        for entry in getattr(resp, "data", []) or []:
            model_id = getattr(entry, "id", None) or getattr(entry, "model", None)
            if not isinstance(model_id, str):
                continue
            if not model_id.startswith("gpt-"):
                continue
            if any(x in model_id for x in ("-tts", "-audio", "-whisper", "-embedding", "-realtime")):
                continue  # 音声/埋め込み系は除外
            if model_id in seen:
                continue
            seen.add(model_id)
            dynamic.append((model_id, self._label(model_id)))

        dynamic.sort(key=lambda x: x[0], reverse=True)
        dynamic = dynamic[: self.max_models]
        seen = {m for m, _ in dynamic}

        merged: list[tuple[str, str]] = []
        merged.extend(dynamic)
        for item in self.base_choices:
            if len(merged) >= self.max_models:
                break
            if item[0] in seen:
                continue
            merged.append(item)
            seen.add(item[0])
        if not merged:
            merged = self.base_choices
        self.completed.emit(merged)

    def _label(self, model_id: str) -> str:
        if "5.2" in model_id:
            return f"{model_id}（最新・高精度）"
        if "4.1" in model_id and "mini" not in model_id:
            return f"{model_id}（高精度）"
        if "4o" in model_id and "mini" not in model_id:
            return f"{model_id}（マルチモーダル対応）"
        if "mini" in model_id:
            return f"{model_id}（軽量）"
        return model_id


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("地質調査報告書 自動生成アプリ（MVP）")
        if DEFAULT_ICON.exists():
            self.setWindowIcon(QIcon(str(DEFAULT_ICON)))

        self.setMinimumSize(1280, 820)

        self._initial_center_done = False

        self.booklet_index_path: Path | None = self._auto_detect_booklet_index_path()
        self.booklet_out_dir: Path = Path(
            os.environ.get("REPORTGEN_BOOKLET_OUTDIR", str(Path.cwd() / "booklets"))
        ).expanduser()
        self.booklet_candidate_count = max(1, int(os.environ.get("REPORTGEN_BOOKLET_CANDIDATES", "2")))
        self.booklet_buffer_m = max(0.0, float(os.environ.get("REPORTGEN_BOOKLET_BUFFER", "200")))
        self.booklet_code_field = os.environ.get("REPORTGEN_BOOKLET_CODE_FIELD", "code")
        self.booklet_name_field = os.environ.get("REPORTGEN_BOOKLET_NAME_FIELD", "name")
        self.default_out_dir = Path(os.environ.get("REPORTGEN_OUT_DIR", str(Path.cwd() / "output"))).expanduser()
        self.default_out_dir.mkdir(parents=True, exist_ok=True)
        self.ai_model_choices: list[tuple[str, str]] = [
            ("gpt-5.2", "gpt-5.2（最新・高精度）"),
            ("gpt-4.1", "gpt-4.1（高精度）"),
            ("gpt-4.1-mini", "gpt-4.1-mini（高速・安価）"),
            ("gpt-4o", "gpt-4o（マルチモーダル対応）"),
            ("gpt-4o-mini", "gpt-4o-mini（軽量）"),
        ]
        self.latest_ai_model = self.ai_model_choices[0][0]
        self.default_ai_model = os.environ.get("REPORTGEN_AI_MODEL", self.latest_ai_model)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)

        root = QWidget()
        scroll.setWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(28, 28, 28, 28)
        root_layout.setSpacing(22)

        root_layout.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(22)
        root_layout.addLayout(body)

        left_col = QVBoxLayout()
        left_col.setSpacing(20)
        body.addLayout(left_col, 3)

        right_col = QVBoxLayout()
        right_col.setSpacing(20)
        body.addLayout(right_col, 2)

        inputs_box = QGroupBox("入力ファイル")
        self._style_group_box(inputs_box)
        inputs_layout = QGridLayout()
        inputs_layout.setHorizontalSpacing(12)
        inputs_layout.setVerticalSpacing(12)
        inputs_layout.setContentsMargins(18, 24, 18, 18)
        inputs_box.setLayout(inputs_layout)
        inputs_layout.setColumnStretch(1, 1)
        left_col.addWidget(inputs_box)

        self.ed_xml, btn_xml = self._build_path_row(self.pick_xml, (".xml",), "XML をドラッグ＆ドロップ")
        inputs_layout.addWidget(QLabel("📄 ボーリングXML"), 0, 0)
        inputs_layout.addWidget(self.ed_xml, 0, 1)
        inputs_layout.addWidget(btn_xml, 0, 2)

        self.ed_pdf, btn_pdf = self._build_path_row(self.pick_pdf, (".pdf",), "液状化判定 PDF（任意）")
        inputs_layout.addWidget(QLabel("🧾 液状化PDF（任意）"), 1, 0)
        inputs_layout.addWidget(self.ed_pdf, 1, 1)
        inputs_layout.addWidget(btn_pdf, 1, 2)

        self.ed_tpl, btn_tpl = self._build_path_row(self.pick_tpl, (".docx",), "指定しない場合は同梱テンプレートを使用")
        inputs_layout.addWidget(QLabel("🗂️ テンプレ（既定あり）"), 2, 0)
        inputs_layout.addWidget(self.ed_tpl, 2, 1)
        inputs_layout.addWidget(btn_tpl, 2, 2)

        self.ed_out, btn_out = self._build_path_row(self.pick_out, (), "保存先ファイル名を指定")
        inputs_layout.addWidget(QLabel("💾 出力（.docx）"), 3, 0)
        inputs_layout.addWidget(self.ed_out, 3, 1)
        inputs_layout.addWidget(btn_out, 3, 2)

        options_box = QGroupBox("オプション")
        self._style_group_box(options_box)
        options_layout = QVBoxLayout()
        options_layout.setContentsMargins(20, 16, 20, 16)
        options_layout.setSpacing(10)
        options_box.setLayout(options_layout)
        self.chk_open_after = QCheckBox("生成後に出力ファイルを開く")
        options_layout.addWidget(self.chk_open_after)
        left_col.addWidget(options_box)

        ai_box = QGroupBox("AI 文章生成（実験）")
        self._style_group_box(ai_box)
        ai_layout = QGridLayout()
        ai_layout.setContentsMargins(20, 16, 20, 16)
        ai_layout.setHorizontalSpacing(12)
        ai_layout.setVerticalSpacing(12)
        ai_box.setLayout(ai_layout)
        left_col.addWidget(ai_box)

        self.chk_ai_enable = QCheckBox("自由記述に OpenAI API を使用する")
        ai_layout.addWidget(self.chk_ai_enable, 0, 0, 1, 2)

        ai_layout.addWidget(QLabel("🔑 API キー"), 1, 0)
        self.ed_ai_key = QLineEdit()
        self.ed_ai_key.setEchoMode(QLineEdit.Password)
        self.ed_ai_key.setPlaceholderText("sk- から始まるキー")
        self.ed_ai_key.setText(os.environ.get("OPENAI_API_KEY", ""))
        ai_layout.addWidget(self.ed_ai_key, 1, 1)

        ai_layout.addWidget(QLabel("🤖 モデル名"), 2, 0)
        self.cmb_ai_model = QComboBox()
        self.cmb_ai_model.setInsertPolicy(QComboBox.NoInsert)
        self.cmb_ai_model.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._populate_ai_models(self.default_ai_model)
        ai_layout.addWidget(self.cmb_ai_model, 2, 1)

        ai_hint = QLabel("※ AI を使う場合は上の「API キー」欄に OpenAI キーを入れてください。未入力時は既定の文章を利用します。")
        ai_hint.setObjectName("aiHint")
        ai_hint.setProperty("class", "hintText")
        ai_hint.setWordWrap(True)
        ai_hint.setStyleSheet("color: #5a6376;")
        ai_layout.addWidget(ai_hint, 3, 0, 1, 2)

        action_box = QGroupBox("生成アクション")
        self._style_group_box(action_box)
        action_layout = QVBoxLayout()
        action_layout.setContentsMargins(20, 20, 20, 20)
        action_layout.setSpacing(16)
        action_box.setLayout(action_layout)
        left_col.addWidget(action_box)

        self.btn_run = QPushButton("報告書を生成")
        self.btn_run.setObjectName("primaryButton")
        self.btn_run.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_run.setMinimumHeight(56)
        self.btn_run.clicked.connect(self.run_generate)
        action_layout.addWidget(self.btn_run)

        self.status_label = QLabel("準備完了")
        self.status_label.setObjectName("statusChip")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        action_layout.addWidget(self.status_label)
        action_layout.addStretch()

        booklet_box = QGroupBox("5万図簿冊ダウンロード")
        self._style_group_box(booklet_box)
        booklet_layout = QVBoxLayout()
        booklet_layout.setContentsMargins(18, 18, 18, 18)
        booklet_layout.setSpacing(12)
        booklet_box.setLayout(booklet_layout)
        left_col.addWidget(booklet_box)

        desc_label = QLabel(
            "ボーリングXMLに含まれる座標（無い場合は住所）から該当する 5万分の1 図幅の簿冊（t.pdf）を自動取得します。"
            "\n図幅インデックスは data/ フォルダ等に配置された GeoJSON/GPKG を自動検出します。"
        )
        desc_label.setWordWrap(True)
        booklet_layout.addWidget(desc_label)

        self.ed_booklet_index = DropLine((".geojson", ".gpkg"))
        self.ed_booklet_index.setPlaceholderText("例: data/indices/50k_index.gpkg / .geojson")
        btn_pick_index = QPushButton("参照")
        btn_pick_index.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        btn_pick_index.clicked.connect(self.pick_booklet_index)

        index_row = QHBoxLayout()
        index_row.addWidget(self.ed_booklet_index)
        index_row.addWidget(btn_pick_index)
        booklet_layout.addWidget(QLabel("図幅インデックスファイル"))
        booklet_layout.addLayout(index_row)

        self.booklet_paths_label = QLabel("")
        self.booklet_paths_label.setWordWrap(True)
        self.booklet_paths_label.setStyleSheet("color: #5a6376;")
        booklet_layout.addWidget(self.booklet_paths_label)

        self.ed_address = QLineEdit()
        self.ed_address.setPlaceholderText("XMLに座標が無い場合のみに使用（例：大阪府箕面市…）")
        booklet_layout.addWidget(QLabel("住所（任意）"))
        booklet_layout.addWidget(self.ed_address)

        self.chk_booklet_all = QCheckBox("候補をすべて保存（デフォルトは最優先1件のみ）")
        booklet_layout.addWidget(self.chk_booklet_all)

        self.btn_fetch_booklet = QPushButton("簿冊（t.pdf）を取得")
        self.btn_fetch_booklet.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.btn_fetch_booklet.setMinimumHeight(48)
        self.btn_fetch_booklet.clicked.connect(self.run_fetch_booklet)
        booklet_layout.addWidget(self.btn_fetch_booklet)

        self.booklet_status_label = QLabel("待機中")
        self.booklet_status_label.setObjectName("statusChip")
        self.booklet_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        booklet_layout.addWidget(self.booklet_status_label)

        log_box = QGroupBox("アクティビティログ")
        self._style_group_box(log_box)
        log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(20, 20, 20, 20)
        log_layout.setSpacing(12)
        log_box.setLayout(log_layout)
        right_col.addWidget(log_box, 1)

        self.txt_log = QTextBrowser()
        self.txt_log.setOpenExternalLinks(True)
        self.txt_log.setPlaceholderText("処理状態や抽出結果がここに表示されます。")
        self.txt_log.setMinimumHeight(340)
        self._apply_emoji_font(self.txt_log)
        log_layout.addWidget(self.txt_log)

        booklet_result_box = QGroupBox("簿冊取得結果")
        self._style_group_box(booklet_result_box)
        booklet_result_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        booklet_result_layout = QVBoxLayout()
        booklet_result_layout.setContentsMargins(20, 20, 20, 20)
        booklet_result_layout.setSpacing(12)
        booklet_result_box.setLayout(booklet_result_layout)
        right_col.addWidget(booklet_result_box, 1)

        self.txt_booklet_results = QTextBrowser()
        self.txt_booklet_results.setPlaceholderText("簿冊取得の結果がここに表示されます。")
        booklet_result_layout.addWidget(self.txt_booklet_results)

        self.booklet_source_label = QLabel(BOOKLET_SOURCE_TEXT)
        self.booklet_source_label.setWordWrap(True)
        self.booklet_source_label.setStyleSheet("color: #5a6376;")
        booklet_result_layout.addWidget(self.booklet_source_label)

        right_col.addStretch(1)

        self._apply_styles()
        QTimer.singleShot(0, self._center_on_screen)

        # 既定テンプレを自動セット（ユーザー上書き>同梱）
        default_tpl = resolve_template_path(None)
        self.ed_tpl.setText(str(default_tpl))

        self.ed_out.setText(str(self.default_out_dir / "生成_報告書.docx"))
        if self.booklet_index_path:
            self.ed_booklet_index.setText(str(self.booklet_index_path))
        self._update_booklet_paths_label()
        self.booklet_thread: QThread | None = None
        self.booklet_worker: BookletFetchWorker | None = None
        self.model_thread: QThread | None = None
        self.model_worker: ModelFetchWorker | None = None

        self._update_booklet_paths_label()
        self.tempdir = Path(tempfile.mkdtemp(prefix="reportgen_"))
        self._start_ai_model_refresh()

    # ---- file pickers -------------------------------------------------
    def pick_xml(self):
        f, _ = QFileDialog.getOpenFileName(self, "XML を選択", "", "XML (*.xml)")
        if f:
            self.ed_xml.setText(f)

    def pick_pdf(self):
        f, _ = QFileDialog.getOpenFileName(self, "液状化PDF を選択", "", "PDF (*.pdf)")
        if f:
            self.ed_pdf.setText(f)

    def pick_tpl(self):
        f, _ = QFileDialog.getOpenFileName(self, "テンプレ（.docx）", "", "Word (*.docx)")
        if f:
            self.ed_tpl.setText(f)

    def pick_out(self):
        f, _ = QFileDialog.getSaveFileName(
            self,
            "出力先",
            str(self.default_out_dir / "生成_報告書.docx"),
            "Word (*.docx)",
        )
        if f:
            self.ed_out.setText(f)

    def pick_booklet_index(self):
        filters = "GeoPackage (*.gpkg);;GeoJSON (*.geojson);;All (*.*)"
        f, _ = QFileDialog.getOpenFileName(self, "図幅インデックスを選択", str(Path.cwd()), filters)
        if f:
            self.ed_booklet_index.setText(f)
            self.booklet_index_path = Path(f)
            self._update_booklet_paths_label()

    def _gather_ai_options(self) -> AIOptions | None:
        if not self.chk_ai_enable.isChecked():
            return None

        api_key = self.ed_ai_key.text().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("AI 文章生成を利用する場合は OpenAI API キーを入力してください。")

        model = (self.cmb_ai_model.currentData() or self.latest_ai_model) or self.default_ai_model
        return AIOptions(enabled=True, api_key=api_key, model=model)

    # ---- utils --------------------------------------------------------
    def log(self, s: str, level: str = "info"):
        colors = {
            "info": "#30435a",
            "warn": "#b46900",
            "error": "#b8323c",
            "success": "#1d7845",
        }
        icons = {
            "info": "ℹ️",
            "warn": "⚠️",
            "error": "⛔",
            "success": "✅",
        }
        fallback_icons = {
            "info": "[i]",
            "warn": "[!]",
            "error": "[x]",
            "success": "[ok]",
        }
        color = colors.get(level, colors["info"])
        icon = icons.get(level, icons["info"]) or fallback_icons.get(level, "[i]")
        escaped = html.escape(s)
        prefix = f"{icon} "
        if "\n" in s:
            self.txt_log.append(f"<pre style='margin:0;color:{color};'>{prefix}{escaped}</pre>")
        else:
            self.txt_log.append(f"<span style='color:{color};'>{prefix}{escaped}</span>")

    # ---- main action --------------------------------------------------
    def run_generate(self):
        self._set_busy(True, "入力を検証中…")
        QApplication.processEvents()
        try:
            xml = Path(self.ed_xml.text().strip())
            pdf_text = self.ed_pdf.text().strip()
            pdf = Path(pdf_text) if pdf_text else None

            tpl_text = self.ed_tpl.text().strip()
            tpl = resolve_template_path(tpl_text or None)  # ←空でも既定が返る

            out_text = self.ed_out.text().strip()
            out = Path(out_text) if out_text else self.default_out_dir / "生成_地質調査報告書.docx"
            out = out.expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out = self._resolve_unique_out_path(out)

            if not xml.exists():
                raise FileNotFoundError("XML が見つかりません")

            self._set_busy(True, "XML を解析中…")
            QApplication.processEvents()

            ai_options = self._gather_ai_options()

            # --- XML → コンテキスト構築 ---
            context = build_context_from_inputs(str(xml), ai_options=ai_options, log_func=self.log)
            if ai_options and ai_options.enabled:
                self.log(f"[AI] {ai_options.model} を使用して自由記述を生成しました。")

            self.log(
                "[XML] site_name="
                f"{context.get('site_name', '')} GW={context.get('groundwater', '')} 層={len(context.get('layers', []))}"
            )
            self.log(
                "[COVER] title="
                f"{context.get('cover_title', '')} date={context.get('cover_date_ym', '')} company={context.get('cover_company_name', '')}"
            )

            # --- PDF（任意） ---
            liq = {"cases": {}}
            if pdf and pdf.exists():
                self._set_busy(True, "PDF を解析中…")
                QApplication.processEvents()
                liq = summarize_liquefaction_pdf(pdf)
                cases = liq.get("cases", {})
                if cases:
                    for acc in sorted(cases):
                        case = cases[acc]
                        self.log(
                            f"[PDF] αmax={acc}gal Dcy={case.displacement_text_fixed}m "
                            f"PL={case.pl_text} 判定={case.risk}"
                        )
                else:
                    self.log("[PDF] 解析結果を取得できませんでした", level="warn")
            else:
                self.log("[PDF] 入力なし（今回は空で生成）", level="warn")

            # --- コンテキスト合成 ---
            self._set_busy(True, "テンプレートへ適用中…")
            QApplication.processEvents()
            cases = liq.get("cases", {})
            if cases:
                is_legacy_template = tpl.name == "報告書_ひな形.docx"
                for acc in (150, 200, 350):
                    case = cases.get(acc)
                    if not case:
                        continue
                    context[f"liq_ground_displacement_{acc}"] = case.displacement_text_fixed
                    context[f"liq_degree_{acc}"] = case.degree
                    context[f"liq_index_{acc}"] = case.pl_text
                    context[f"liq_risk_{acc}"] = case.risk

                summary_text = (liq.get("summary_text") or "").strip()
                if summary_text and not is_legacy_template:
                    context["liq_summary_text"] = summary_text

                conclusion_text = (liq.get("conclusion_text") or "").strip()
                if conclusion_text and not is_legacy_template:
                    context["liq_conclusion_text"] = conclusion_text

                risk_text = (liq.get("risk_text") or "").strip()
                if risk_text and not is_legacy_template:
                    context["liq_risk_evaluation"] = risk_text

                # 旧テンプレ互換: 該当プレースホルダを空埋めし、後処理で数値差し替え
                context["liq_summary"] = ""
                context["liq_conclusion"] = ""
                if is_legacy_template:
                    context["liq_summary_text"] = ""
                    context["liq_conclusion_text"] = ""
                    context["liq_risk_evaluation"] = ""

            # --- 生成 ---
            generate_docx_from_template(str(tpl), str(out), context, liq_result=liq, source_xml_path=str(xml))
            QMessageBox.information(self, "完了", f"出力しました：\n{out}")
            self.log(f"[OK] {out}", level="success")

            if self.chk_open_after.isChecked():
                self._open_generated(out)

            self._set_busy(False, "完了しました")

        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
            self.log(str(e), level="error")
            self.log(traceback.format_exc(), level="error")
            self._set_busy(False, "エラーが発生しました")

    # ---- booklet fetcher ---------------------------------------------
    def run_fetch_booklet(self):
        if self.booklet_thread:
            QMessageBox.information(self, "実行中", "簿冊取得が進行中です。完了をお待ちください。")
            return

        xml_text = self.ed_xml.text().strip()
        if not xml_text:
            QMessageBox.warning(self, "入力エラー", "ボーリングXMLを指定してください。")
            return
        xml_path = Path(xml_text)
        if not xml_path.exists():
            QMessageBox.warning(self, "入力エラー", "指定された XML が存在しません。")
            return

        index_path = self._resolve_booklet_index_path()
        if not index_path:
            QMessageBox.warning(
                self,
                "インデックス未検出",
                "図幅インデックスファイルが見つかりません。data/indices/50k_index.gpkg（または .geojson）を配置するか、"
                "環境変数 REPORTGEN_BOOKLET_INDEX でパスを指定するか、この画面で参照ボタンから選択してください。",
            )
            return

        out_dir = self._resolve_booklet_out_dir()

        address = self.ed_address.text().strip()

        params = BookletFetchParams(
            index_path=index_path,
            out_dir=out_dir,
            xml_path=xml_path,
            address=address,
            candidate_count=self.booklet_candidate_count,
            buffer_m=self.booklet_buffer_m,
            select_mode="all" if self.chk_booklet_all.isChecked() else "best",
            code_field=self.booklet_code_field,
            name_field=self.booklet_name_field,
        )

        self.txt_booklet_results.clear()
        self._set_booklet_busy(True, "簿冊取得を開始しています…")

        self.booklet_thread = QThread(self)
        self.booklet_worker = BookletFetchWorker(params)
        self.booklet_worker.moveToThread(self.booklet_thread)
        self.booklet_thread.started.connect(self.booklet_worker.run)
        self.booklet_worker.progress.connect(self._handle_booklet_progress)
        self.booklet_worker.completed.connect(self._handle_booklet_completed)
        self.booklet_worker.failed.connect(self._handle_booklet_failed)
        self.booklet_worker.completed.connect(self.booklet_thread.quit)
        self.booklet_worker.failed.connect(self.booklet_thread.quit)
        self.booklet_worker.completed.connect(self.booklet_worker.deleteLater)
        self.booklet_worker.failed.connect(self.booklet_worker.deleteLater)
        self.booklet_thread.finished.connect(self._cleanup_booklet_thread)
        self.booklet_thread.start()

    def _handle_booklet_progress(self, message: str):
        self.booklet_status_label.setText(message)

    def _handle_booklet_completed(self, result: BookletFetchResult):
        self._render_booklet_result(result)
        self._set_booklet_busy(False, "簿冊取得が完了しました")

    def _handle_booklet_failed(self, message: str):
        self._set_booklet_busy(False, "簿冊取得に失敗しました")
        QMessageBox.warning(self, "簿冊取得エラー", message)

    def _render_booklet_result(self, result: BookletFetchResult):
        lines: list[str] = []
        lines.append(f"座標: lat={result.lat:.6f}, lon={result.lon:.6f}")

        attempted = [c for c in result.candidates if c.attempted]
        if attempted:
            lines.append("保存結果:")
            for cand in attempted:
                if cand.success and cand.saved_path:
                    lines.append(f"  - 保存成功: {cand.code}t.pdf（{cand.name}）→ {cand.saved_path}")
                else:
                    reason = cand.error or "理由不明"
                    lines.append(f"  - 保存失敗: {cand.code}t.pdf（{cand.name}）: {reason}")
        else:
            lines.append("保存対象: 0 件（best モードで候補が不足）")

        summary_parts = [
            f"{cand.code}（{cand.name}）距離{int(round(cand.distance_m))}m"
            for cand in result.candidates
        ]
        if summary_parts:
            lines.append("候補: " + "、".join(summary_parts))
        lines.append("")
        lines.append(BOOKLET_SOURCE_TEXT)
        self.txt_booklet_results.setPlainText("\n".join(lines))

    def _set_booklet_busy(self, busy: bool, message: str):
        self.btn_fetch_booklet.setDisabled(busy)
        self.chk_booklet_all.setDisabled(busy)
        self.ed_address.setDisabled(busy)
        self.booklet_status_label.setText(message)

    def _cleanup_booklet_thread(self):
        if self.booklet_thread:
            self.booklet_thread.deleteLater()
            self.booklet_thread = None
        self.booklet_worker = None

    def _update_booklet_paths_label(self):
        if not hasattr(self, "booklet_paths_label"):
            return
        text_field = ""
        if hasattr(self, "ed_booklet_index"):
            text_field = self.ed_booklet_index.text().strip()
        index_display = text_field or (
            str(self.booklet_index_path)
            if self.booklet_index_path and self.booklet_index_path.exists()
            else "未検出：data/indices/50k_index.gpkg（または .geojson）を指定してください"
        )
        out_dir_text = str(self.booklet_out_dir)
        self.booklet_paths_label.setText(f"インデックス: {index_display}\n保存先: {out_dir_text}")

    def _auto_detect_booklet_index_path(self) -> Path | None:
        env = os.environ.get("REPORTGEN_BOOKLET_INDEX")
        if env:
            p = Path(env).expanduser()
            if p.exists():
                return p
        candidates = [
            Path.cwd() / "data" / "indices" / "50k_index.gpkg",
            Path.cwd() / "data" / "indices" / "50k_index.geojson",
            Path.cwd() / "data" / "5man_index.geojson",
            Path.cwd() / "data" / "5man_index.gpkg",
            Path.cwd() / "data" / "index.geojson",
            Path.cwd() / "data" / "index.gpkg",
        ]
        for cand in candidates:
            if cand.exists():
                return cand
        return None

    def _resolve_booklet_index_path(self) -> Path | None:
        user_text = ""
        if hasattr(self, "ed_booklet_index"):
            user_text = self.ed_booklet_index.text().strip()
        if user_text:
            p = Path(user_text).expanduser()
            if p.exists():
                self.booklet_index_path = p
                return p
        if self.booklet_index_path and self.booklet_index_path.exists():
            return self.booklet_index_path
        auto = self._auto_detect_booklet_index_path()
        self.booklet_index_path = auto
        if auto and hasattr(self, "ed_booklet_index") and not user_text:
            self.ed_booklet_index.setText(str(auto))
        self._update_booklet_paths_label()
        return auto

    def _resolve_booklet_out_dir(self) -> Path:
        path = self.booklet_out_dir.expanduser()
        path.mkdir(parents=True, exist_ok=True)
        self.booklet_out_dir = path
        self._update_booklet_paths_label()
        return path

    def _start_ai_model_refresh(self):
        api_key = self.ed_ai_key.text().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return  # キー未入力時は静的リストのみ利用
        if self.model_thread:
            return
        self.log("[AI] モデル一覧を取得しています…")
        self.model_thread = QThread(self)
        self.model_worker = ModelFetchWorker(api_key, self.ai_model_choices.copy(), max_models=10)
        self.model_worker.moveToThread(self.model_thread)
        self.model_thread.started.connect(self.model_worker.run)
        self.model_worker.completed.connect(self._handle_model_refresh)
        self.model_worker.failed.connect(self._handle_model_refresh_failed)
        self.model_worker.completed.connect(self.model_thread.quit)
        self.model_worker.failed.connect(self.model_thread.quit)
        self.model_worker.completed.connect(self.model_worker.deleteLater)
        self.model_worker.failed.connect(self.model_worker.deleteLater)
        self.model_thread.finished.connect(self._cleanup_model_thread)
        self.model_thread.start()

    def _handle_model_refresh(self, choices: list[tuple[str, str]]):
        self.ai_model_choices = choices
        if choices:
            self.latest_ai_model = choices[0][0]
        current = self.cmb_ai_model.currentData() or self.default_ai_model or self.latest_ai_model
        self._populate_ai_models(current)
        self.log(f"[AI] モデル一覧を更新しました（{len(choices)}件）。", level="success")

    def _handle_model_refresh_failed(self, message: str):
        self.log(f"[AI] モデル一覧の取得に失敗しました: {message}", level="warn")

    def _cleanup_model_thread(self):
        if self.model_thread:
            self.model_thread.deleteLater()
            self.model_thread = None
        self.model_worker = None

    def _populate_ai_models(self, selected_model: str | None):
        if not hasattr(self, "cmb_ai_model"):
            return
        self.cmb_ai_model.clear()
        seen: set[str] = set()
        for model, label in self.ai_model_choices:
            self.cmb_ai_model.addItem(label, model)
            seen.add(model)

        selected = selected_model or self.latest_ai_model
        if selected not in seen:
            self.cmb_ai_model.addItem(selected, selected)

        idx = self.cmb_ai_model.findData(selected)
        if idx < 0:
            idx = 0
        self.cmb_ai_model.setCurrentIndex(idx)

    def _style_group_box(self, box: QGroupBox):
        font = box.font()
        font.setPointSize(20)
        font.setBold(True)
        box.setFont(font)

    def _resolve_unique_out_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix or ".docx"
        parent = path.parent
        for i in range(1, 1000):
            candidate = parent / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                return candidate
        return path

    def _apply_emoji_font(self, widget: QWidget):
        try:
            font = widget.font()
            families = [
                "Segoe UI Emoji",
                "Noto Color Emoji",
                "Apple Color Emoji",
                "Segoe UI Symbol",
                font.family(),
            ]
            if hasattr(font, "setFamilies"):
                font.setFamilies(families)
            else:  # fallback for older Qt
                font.setFamily(", ".join(families))
            widget.setFont(font)
        except Exception:
            pass

    # ---- ui helpers ---------------------------------------------------
    def _build_header(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        icon_label = QLabel()
        icon_label.setFixedSize(54, 54)
        if DEFAULT_ICON.exists():
            pix = QIcon(str(DEFAULT_ICON)).pixmap(54, 54)
            icon_label.setPixmap(pix)
        else:
            icon_label.setPixmap(self.style().standardIcon(QStyle.SP_FileDialogInfoView).pixmap(48, 48))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label, 0, Qt.AlignTop)

        title = QLabel("地質調査報告書 自動生成アプリ")
        title.setObjectName("heroTitle")
        subtitle = QLabel("ボーリング XML と液状化判定 PDF から、テンプレートを用いて Word レポートを生成します。")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")

        text_block = QVBoxLayout()
        text_block.setSpacing(6)
        text_block.addWidget(title)
        text_block.addWidget(subtitle)
        layout.addLayout(text_block, 1)

        layout.addStretch(1)
        return layout

    def _build_path_row(self, handler, patterns, placeholder):
        line = DropLine(patterns)
        if placeholder:
            line.setPlaceholderText(placeholder)
        button = QPushButton("参照")
        button.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        button.setMinimumHeight(52)
        button.clicked.connect(handler)
        return line, button

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #f5f7fb;
                font-size: 19px;
            }
            QLabel#heroTitle {
                font-size: 32px;
                font-weight: 600;
                color: #24324b;
            }
            QLabel#heroSubtitle {
                font-size: 19px;
                color: #5a6376;
            }
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #d5dae4;
                border-radius: 12px;
                margin-top: 16px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 22px;
                padding: 0 6px;
                color: #3a435c;
                font-size: 21px;
                font-weight: 700;
            }
            QGroupBox QLabel {
                font-size: 18px;
                color: #3a435c;
                font-weight: 500;
            }
            QCheckBox {
                font-size: 18px;
                color: #3a435c;
            }
            QComboBox, QLabel {
                font-size: 18px;
            }
            QLabel#heroTitle {
                font-size: 32px;
                font-weight: 600;
                color: #24324b;
            }
            QLabel#heroSubtitle {
                font-size: 19px;
                color: #5a6376;
            }
            QLabel#statusChip {
                border-radius: 13px;
                padding: 14px 26px;
                background-color: #e8ecf7;
                color: #3a435c;
                font-size: 17px;
                letter-spacing: 0.3px;
            }
            QLabel.hintText {
                font-size: 17px;
                color: #5a6376;
            }
            QLineEdit, QTextBrowser {
                border: 1px solid #c8cfdb;
                border-radius: 8px;
                padding: 14px 18px;
                background-color: #fbfcff;
                font-size: 19px;
            }
            QLineEdit:focus, QTextBrowser:focus {
                border: 1px solid #4d7cff;
                background-color: #ffffff;
            }
            QPushButton {
                border-radius: 8px;
                padding: 16px 30px;
                font-size: 19px;
            }
            QPushButton#primaryButton {
                background-color: #4d7cff;
                color: #ffffff;
                font-weight: 600;
                border: none;
            }
            QPushButton#primaryButton:hover {
                background-color: #3f6ce0;
            }
            QPushButton#primaryButton:pressed {
                background-color: #355dcc;
            }
            QPushButton#primaryButton:disabled {
                background-color: #dce2ef;
                color: #8a94a9;
            }
        """
        )

    def _center_on_screen(self):
        primary = QGuiApplication.primaryScreen()
        screen = primary or self.screen()
        if not screen:
            return

        available = screen.availableGeometry()
        if not available.isValid():
            return

        frame_size = self.frameGeometry().size()
        inner_size = self.rect().size()
        decorations = frame_size - inner_size
        deco_w = max(0, decorations.width())
        deco_h = max(0, decorations.height())

        if inner_size.width() <= 0 or inner_size.height() <= 0:
            self.resize(1280, 820)
            frame_size = self.frameGeometry().size()
            inner_size = self.rect().size()
            decorations = frame_size - inner_size
            deco_w = max(0, decorations.width())
            deco_h = max(0, decorations.height())

        width_upper = max(available.width() - deco_w - 60, 1200)
        height_upper = max(available.height() - deco_h - 60, 820)

        target_width = max(min(int(available.width() * 0.75), width_upper), 1200)
        target_height = max(min(int(available.height() * 0.75), height_upper), 820)
        self.resize(target_width, target_height)

        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        top_left = frame.topLeft()
        left_bound = available.x() + 20
        right_bound = available.x() + available.width() - self.width() - 20
        top_bound = available.y() + 20
        bottom_bound = available.y() + available.height() - self.height() - 20
        if right_bound < left_bound:
            right_bound = left_bound
        if bottom_bound < top_bound:
            bottom_bound = top_bound
        top_left.setX(min(max(top_left.x(), left_bound), right_bound))
        top_left.setY(min(max(top_left.y(), top_bound), bottom_bound))
        self.move(top_left)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_center_done:
            self._initial_center_done = True
            self._center_on_screen()

    def _set_busy(self, busy: bool, message: str):
        self.status_label.setText(message)
        self.btn_run.setDisabled(busy)

    def _open_generated(self, path: Path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            self.log(f"[WARN] 自動でファイルを開けませんでした: {exc}", level="warn")


def main():
    app = QApplication(sys.argv)
    if DEFAULT_ICON.exists():
        app.setWindowIcon(QIcon(str(DEFAULT_ICON)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
