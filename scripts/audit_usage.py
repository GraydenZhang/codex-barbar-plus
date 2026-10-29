"""Checked usage aggregation corrections applied after the original Plus overlay."""
from pathlib import Path


def apply(source: Path) -> None:
    path = source / "rust/src/usage_spend.rs"
    text = path.read_text(encoding="utf-8-sig")
    old = "total_tokens: totals.0 + totals.1 + totals.2,"
    if text.count(old) != 2:
        raise RuntimeError("usage totals: expected model and daily aggregation sites")
    text = text.replace(old, "total_tokens: totals.0.saturating_add(totals.2),")
    old = (
        "        total_tokens: report.summary.input_tokens\n"
        "            + report.summary.cached_tokens\n"
        "            + report.summary.output_tokens,"
    )
    if text.count(old) != 1:
        raise RuntimeError("usage totals: expected one report aggregation site")
    text = text.replace(old, (
        "        // Cached input is a subset of input, not additional tokens.\n"
        "        total_tokens: report.summary.input_tokens\n"
        "            .saturating_add(report.summary.output_tokens),"
    ))
    marker = "    #[test]\n    fn malformed_lines_are_counted_without_content()"
    if text.count(marker) != 1:
        raise RuntimeError("usage totals: regression test insertion point missing")
    test = '''    #[test]
    fn cached_input_is_not_counted_twice_in_summary_model_or_day() {
        let root = fixture_root();
        // Mirrors the relationship in real Codex token_count records:
        // input 521505 includes cached 365056; total is input + output 771.
        write_fixture(
            root.path(), "2026-08-20", "cached.jsonl",
            &(token_line("2026-08-20T12:00:00Z", "gpt-test", 521_505, 365_056, 771) + "\\n"),
        );
        let scanner = CostScanner::new(30)
            .with_cache_root(root.path().join("cache"))
            .with_sessions_dirs(vec![root.path().join("sessions")]);
        let report = scanner.scan_codex_range_detailed(
            &range("2026-08-20", "2026-08-20"), None,
        ).unwrap();
        let converted = convert_report(
            report, range("2026-08-20", "2026-08-20"), &fixture_catalog("gpt-test"),
        );
        assert_eq!(converted.input_tokens, 521_505);
        assert_eq!(converted.cached_input_tokens, 365_056);
        assert_eq!(converted.total_tokens, 522_276);
        assert_eq!(converted.models[0].total_tokens, 522_276);
        assert_eq!(converted.daily[0].total_tokens, 522_276);
        // Cost still treats cached tokens at their separate rate.
        assert!((converted.estimated_cost_usd.unwrap() - 0.684_122).abs() < 1e-9);
    }

'''
    text = text.replace(marker, test + marker)
    path.write_text(text, encoding="utf-8")
