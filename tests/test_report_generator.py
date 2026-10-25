"""
Tests for the HTML/CSV report output.
"""

import pytest

from k_sites.reporting.report_generator import (
    _safety_class,
    _safety_label,
    generate_html_report,
)


def gene(symbol, level):
    return {
        "symbol": symbol, "pleiotropy_score": 2.0, "specificity_score": 0.8, "composite_score": 0.5,
        "kegg_pathway_count": 3,
        "safety_recommendation": {"safety_level": level, "primary_recommendation": "Standard Knockout",
                                  "justification": ["ok"], "concerns": [], "mitigation_strategies": []},
    }


class TestSafetyBadges:
    @pytest.mark.parametrize("level,css,label", [
        ("SAFE", "safety-safe", "Safe"),
        ("CAUTION", "safety-caution", "Caution"),
        ("MODERATE_CONCERN", "safety-concern", "Moderate concern"),
        ("HIGH_CONCERN", "safety-warning", "High concern"),
        ("AVOID", "safety-critical", "Avoid"),
    ])
    def test_every_real_level_has_its_own_colour_and_readable_label(self, level, css, label):
        assert _safety_class(level) == css
        assert _safety_label(level) == label

    def test_levels_get_distinct_colours(self):
        levels = ["SAFE", "CAUTION", "MODERATE_CONCERN", "HIGH_CONCERN", "AVOID"]
        assert len({_safety_class(level) for level in levels}) == 5

    def test_unknown_level_is_grey_not_green(self):
        assert _safety_class("") == "safety-unknown"
        assert _safety_class(None) == "safety-unknown"
        assert _safety_class("SOMETHING_NEW") == "safety-unknown"
        assert _safety_label(None) == "Unknown"


class TestHtmlReport:
    def render(self, tmp_path, data):
        out = tmp_path / "report.html"
        generate_html_report(data, str(out))
        return out.read_text(encoding="utf-8")

    def base(self, **extra):
        data = {"metadata": {"go_term": "GO:0006281", "organism": "9606", "max_pleiotropy": 7},
                "genes": [gene("A", "SAFE"), gene("B", "MODERATE_CONCERN")],
                "statistics": {"total_genes_screened": 40}}
        data.update(extra)
        return data

    def test_badges_use_the_right_class_and_text(self, tmp_path):
        html_text = self.render(tmp_path, self.base())

        assert 'class="safety-level safety-safe">Safe<' in html_text
        assert 'class="safety-level safety-concern">Moderate concern<' in html_text
        assert "MODERATE_CONCERN<" not in html_text

    def test_coverage_warning_is_shown_prominently(self, tmp_path):
        html_text = self.render(tmp_path, self.base(
            warnings=["Only 39% of annotations were read (2,000 of 5,120)."]))

        assert '<div class="report-warning">' in html_text
        assert "Only 39% of annotations were read" in html_text

    def test_no_warning_box_when_everything_was_read(self, tmp_path):
        html_text = self.render(tmp_path, self.base(warnings=[]))

        assert '<div class="report-warning">' not in html_text

    def test_screened_count_comes_from_the_statistics(self, tmp_path):
        html_text = self.render(tmp_path, self.base())

        assert 'summary-value">40</div>' in html_text

    def test_cutoff_is_labelled_as_a_zero_to_ten_score(self, tmp_path):
        html_text = self.render(tmp_path, self.base())

        assert "Pleiotropy cutoff (0-10): <strong>7</strong>" in html_text

    def test_warning_is_written_to_the_csv_header(self, tmp_path):
        self.render(tmp_path, self.base(warnings=["Only 39% of annotations were read."]))

        csv_text = (tmp_path / "report_comprehensive.csv").read_text(encoding="utf-8")
        assert "# WARNING: Only 39% of annotations were read." in csv_text
