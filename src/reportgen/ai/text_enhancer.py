from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore


SYSTEM_PROMPT = (
    "You are an expert Japanese technical writer for geotechnical engineering reports. "
    "Respond with natural Japanese sentences suitable for direct placement inside a report. "
    "Avoid bullet lists unless explicitly requested and output plain text."
)


SECTION_PROMPTS: dict[str, dict[str, str]] = {
    "drilling_summary": {
        "label": "調査概要",
        "instructions": (
            "ボーリング仕様、深度、採取したデータのポイントを2〜4文で要約してください。"
            "固有名詞や測定値は可能な範囲で盛り込んでください。"
        ),
    },
    "groundwater_overview": {
        "label": "地下水状況",
        "instructions": (
            "地下水位の測定結果や観測状況、注意点を記述してください。測定日や基準深度が"
            "分かる場合は含めてください。"
        ),
    },
    "foundation_consideration_top": {
        "label": "基礎検討（表層）",
        "instructions": (
            "表層付近の層構成と支持力の観点から、基礎設計時の留意点を2〜3文で記述してください。"
        ),
    },
    "foundation_consideration_bottom": {
        "label": "基礎検討（下層）",
        "instructions": (
            "中層〜深層の地盤状態や支持層の性状に触れつつ、沈下・液状化などの観点を含めた"
            "助言を2〜3文で述べてください。"
        ),
    },
}


@dataclass
class AIOptions:
    enabled: bool = False
    api_key: str | None = None
    model: str = "gpt-5.2"
    temperature: float = 0.2
    target_sections: tuple[str, ...] = field(
        default_factory=lambda: tuple(SECTION_PROMPTS.keys())
    )

    def resolved_api_key(self) -> str | None:
        return (self.api_key or "").strip() or os.environ.get("OPENAI_API_KEY")


class AITextGenerationError(RuntimeError):
    """Raised when AI text generation fails."""


class AITextEnhancer:
    def __init__(
        self,
        options: AIOptions,
        logger: Callable[[str], Any] | None = None,
    ):
        self.options = options
        self.logger = logger

    def enhance_context(
        self,
        base_context: Mapping[str, Any],
        metadata: Mapping[str, Any],
        boring: Mapping[str, Any],
    ) -> Dict[str, str]:
        if not self.options.enabled:
            return {}
        if OpenAI is None:
            raise AITextGenerationError("openai パッケージがインストールされていません。")

        api_key = self.options.resolved_api_key()
        if not api_key:
            raise AITextGenerationError("OpenAI API キーが設定されていません。")
        try:
            client = OpenAI(api_key=api_key)
        except Exception as exc:  # pragma: no cover - connection errors
            raise AITextGenerationError(f"OpenAI クライアントの初期化に失敗しました: {exc}") from exc

        updates: Dict[str, str] = {}
        for section in self.options.target_sections:
            prompt_meta = SECTION_PROMPTS.get(section)
            if not prompt_meta:
                continue
            prompt = self._compose_prompt(section, prompt_meta, base_context, metadata, boring)
            self._log(f"[AI] {prompt_meta['label']}を生成しています…")
            text = self._request_text(client, prompt)
            if text:
                updates[section] = text
                self._log(f"[AI] {prompt_meta['label']}を更新しました。")
        return updates

    def _request_text(self, client: OpenAI, prompt: str) -> str:
        try:
            response = client.chat.completions.create(
                model=self.options.model,
                temperature=self.options.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as exc:  # pragma: no cover - network errors
            raise AITextGenerationError(f"OpenAI API 呼び出しに失敗しました: {exc}") from exc

        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            raise AITextGenerationError("OpenAI API から有効な文章が返されませんでした。")
        return text

    def _compose_prompt(
        self,
        section_name: str,
        prompt_meta: Mapping[str, str],
        context: Mapping[str, Any],
        metadata: Mapping[str, Any],
        boring: Mapping[str, Any],
    ) -> str:
        site_name = (
            context.get("site_name")
            or metadata.get("site_name")
            or context.get("survey_location")
            or ""
        )
        location = context.get("survey_location", "")
        drilling_length = context.get("drilling_length", "")
        borehole = context.get("borehole_name", "")
        groundwater_depth = context.get("groundwater_depth", "")
        groundwater_note = context.get("groundwater_note", "")
        natural_depth = context.get("natural_drilling_depth", "")
        existing = context.get(section_name, "")

        layer_summary = self._summarize_layers(boring.get("layers", []))
        spt_summary = self._summarize_spt(boring.get("spt_records", []))

        overview_lines = [
            f"調査名: {context.get('survey_name', '')}",
            f"地点: {site_name}",
            f"所在地: {location}",
            f"孔名: {borehole}",
            f"掘進長: {drilling_length}",
            f"自然地盤面深度: {natural_depth}",
        ]
        groundwater_lines = [
            f"地下水位: {groundwater_depth}",
            f"備考: {groundwater_note}",
            f"観測欄: {context.get('groundwater', '')}",
        ]

        prompt_sections = [
            f"### セクション: {prompt_meta['label']}",
            f"指示: {prompt_meta['instructions']}",
            "文体: 丁寧な日本語。一人称は使用しない。",
            "制約: 箇条書きは使用しない。150文字以上280文字以下を目安にする。",
            "",
            "## 調査概要",
            "\n".join(overview_lines),
            "",
            "## 地下水情報",
            "\n".join(groundwater_lines),
            "",
            "## 標準貫入試験データ",
            spt_summary or "記録なし",
            "",
            "## 層構成",
            layer_summary or "構成情報なし",
            "",
            "## 既定の文章（参考）",
            existing or "既定の文章は設定されていません。",
            "",
            "## 追加データ(JSON)",
            json.dumps(
                {
                    "metadata": metadata,
                    "context": {
                        "survey_period_start": context.get("survey_period_start", ""),
                        "survey_period_end": context.get("survey_period_end", ""),
                    },
                },
                ensure_ascii=False,
            ),
            "",
            "上記の情報を要約し、指示に従って文章を作成してください。",
        ]
        return "\n".join(prompt_sections)

    def _summarize_layers(self, layers: Iterable[Mapping[str, Any]]) -> str:
        lines: list[str] = []
        layer_list = list(layers or [])
        for idx, layer in enumerate(layer_list[:8]):
            name = layer.get("name", "")
            top = layer.get("top")
            bottom = layer.get("bottom")
            observation = (layer.get("observation") or "").splitlines()[0:2]
            obs_text = " / ".join(s.strip() for s in observation if s.strip())
            depth = ""
            if top is not None and bottom is not None:
                depth = f"GL-{top:.2f}～{bottom:.2f}m"
            lines.append(f"{idx + 1}. {name} {depth} {obs_text}".strip())
        if len(layer_list) > 8:
            lines.append(f"…ほか {len(layer_list) - 8} 層")
        return "\n".join(lines)

    def _summarize_spt(self, spt_records: Iterable[Mapping[str, Any]]) -> str:
        values: list[str] = []
        for record in (spt_records or []):
            depth = record.get("depth")
            value = record.get("n_value")
            if depth is None or value is None:
                continue
            values.append(f"{depth:.1f}m: N={value}")
            if len(values) >= 8:
                break
        return ", ".join(values)

    def _log(self, message: str):
        if self.logger:
            try:
                self.logger(message)
            except Exception:
                pass
