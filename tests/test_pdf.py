from pathlib import Path

from reportgen.parsers.liquefaction_pdf import summarize_liquefaction_pdf


def test_liquefaction_pdf_sample_extracts_cases():
    pdf_path = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "src"
        / "reportgen"
        / "templates"
        / "液状化判定プリントアウト.pdf"
    )

    result = summarize_liquefaction_pdf(pdf_path)
    cases = result.get("cases", {})

    assert set(cases.keys()) == {150, 200, 350}

    for case in cases.values():
        assert case.degree == "なし"
        assert case.displacement == 0.0
        assert case.pl_value == 0.0
        assert case.risk == "かなり低い"

    summary_text = result.get("summary_text") or ""
    assert "液状化の検討結果は" in summary_text
    assert "FL値" in summary_text

    risk_text = result.get("risk_text") or ""
    assert "かなり低い" in risk_text
