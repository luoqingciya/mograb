# SPDX-License-Identifier: GPL-3.0-only
"""书源 Schema 与语义校验测试（规划书 §10、§11）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mograb.domain.enums import SourceCapability
from mograb.domain.source import ExtractRule, RuleType, SourceSpec, TransformOp
from mograb.errors import SourceSchemaError, SourceUnsupportedError
from mograb.source import lint, load_source_dict, load_source_file

MINIMAL = {
    "spec_version": 1,
    "id": "demo",
    "name": "Demo",
    "version": "1.0.0",
    "capabilities": ["search"],
    "search": {
        "request": {"method": "GET", "url": "https://demo.example.com/s"},
        "result": {"list": ".item", "fields": {"title": ".t", "url": "a@href"}},
    },
}


class TestLoadExampleSource:
    def test_official_example_loads(self, example_source_dir: Path) -> None:
        """官方示例书源必须能通过加载与校验。"""
        spec = load_source_file(example_source_dir / "source.yaml")
        assert spec.id == "example"
        assert spec.spec_version == 1
        assert spec.version == "1.0.0"
        assert spec.supports(SourceCapability.SEARCH)
        assert spec.supports(SourceCapability.CONTENT)

    def test_example_passes_lint(self, example_source_dir: Path) -> None:
        spec = load_source_file(example_source_dir / "source.yaml")
        report = lint(spec)
        assert report.is_ready, [d.format() for d in report.errors]


class TestSchemaValidation:
    def test_minimal_source_is_valid(self) -> None:
        spec = load_source_dict(MINIMAL)
        assert spec.id == "demo"

    def test_invalid_id_rejected(self) -> None:
        with pytest.raises(SourceSchemaError):
            load_source_dict({**MINIMAL, "id": "Bad_ID!"})

    def test_invalid_version_rejected(self) -> None:
        with pytest.raises(SourceSchemaError):
            load_source_dict({**MINIMAL, "version": "1.0"})

    def test_unsupported_spec_version_rejected(self) -> None:
        with pytest.raises((SourceSchemaError, SourceUnsupportedError)):
            load_source_dict({**MINIMAL, "spec_version": 99})

    def test_capability_without_spec_rejected(self) -> None:
        """声明能力但未提供规格必须报错。"""
        data = {**MINIMAL, "capabilities": ["search", "book"]}
        with pytest.raises(SourceSchemaError):
            load_source_dict(data)

    def test_spec_without_capability_rejected(self) -> None:
        """提供规格但未声明能力必须报错。"""
        data = {
            **MINIMAL,
            "capabilities": [],
        }
        with pytest.raises(SourceSchemaError):
            load_source_dict(data)

    def test_script_permission_rejected(self) -> None:
        """v1 禁止书源声明 script 权限（禁止任意代码执行）。"""
        data = {**MINIMAL, "permissions": {"script": True}}
        with pytest.raises(SourceSchemaError):
            load_source_dict(data)

    def test_extra_field_rejected(self) -> None:
        """未知字段必须拒绝，避免拼写错误被静默忽略。"""
        with pytest.raises(SourceSchemaError):
            load_source_dict({**MINIMAL, "unknown_field": 1})

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SourceSchemaError):
            load_source_file(tmp_path / "nope.yaml")


class TestExtractRuleParsing:
    @pytest.mark.parametrize(
        ("raw", "rule_type", "expression", "attribute"),
        [
            (".item", RuleType.CSS, ".item", None),
            ("a@href", RuleType.CSS, "a", "href"),
            ("@text", RuleType.ATTR, "text", None),
            ("xpath://div", RuleType.XPATH, "//div", None),
            ("jsonpath:$.a", RuleType.JSONPATH, "$.a", None),
            ("regex:\\d+", RuleType.REGEX, "\\d+", None),
        ],
    )
    def test_parse(
        self, raw: str, rule_type: RuleType, expression: str, attribute: str | None
    ) -> None:
        rule = ExtractRule.parse(raw)
        assert rule.type is rule_type
        assert rule.expression == expression
        assert rule.attribute == attribute

    def test_raw_roundtrip(self) -> None:
        for raw in (".item", "a@href", "@text", "xpath://div"):
            assert ExtractRule.parse(raw).raw == raw


class TestTransformCoercion:
    def test_string_shorthand(self) -> None:
        spec = SourceSpec.model_validate(
            {
                **MINIMAL,
                "transforms": ["trim", "normalize_whitespace"],
            }
        )
        assert [t.op for t in spec.transforms] == [
            TransformOp.TRIM,
            TransformOp.NORMALIZE_WHITESPACE,
        ]

    def test_dict_shorthand_with_params(self) -> None:
        spec = SourceSpec.model_validate(
            {
                **MINIMAL,
                "transforms": [{"regex_replace": {"pattern": r"\s+", "replacement": " "}}],
            }
        )
        assert spec.transforms[0].op is TransformOp.REGEX_REPLACE
        assert spec.transforms[0].pattern == r"\s+"


class TestLinter:
    def test_reports_missing_search_field(self) -> None:
        data = {
            **MINIMAL,
            "search": {
                "request": {"method": "GET", "url": "https://demo.example.com/s"},
                "result": {"list": ".item", "fields": {"title": ".t"}},  # 缺 url
            },
        }
        report = lint(load_source_dict(data))
        assert not report.is_ready
        assert any("'url'" in d.message for d in report.errors)

    def test_warns_undefined_template_variable(self) -> None:
        data = {
            **MINIMAL,
            "search": {
                "request": {
                    "method": "GET",
                    "url": "https://demo.example.com/s?q={{nope}}",
                },
                "result": {"list": ".item", "fields": {"title": ".t", "url": "a@href"}},
            },
        }
        report = lint(load_source_dict(data))
        assert any("nope" in d.message for d in report.errors)

    def test_warns_unlisted_domain(self) -> None:
        data = {**MINIMAL, "permissions": {"network": ["other.com"]}}
        report = lint(load_source_dict(data))
        assert any("不在 permissions.network" in d.message for d in report.errors)
