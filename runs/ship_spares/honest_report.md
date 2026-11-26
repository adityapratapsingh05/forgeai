# ForgeAI Agent Report: Ship Spares Assistant

**Run Name:** ship_spares  
**Generated:** 2026-11-26 22:50:00  
**Optimizer Iterations:** 0 (initial agent)

---

## Executive Summary

The Ship Spares Assistant agent was successfully built from the provided brief and documentation. The agent can answer questions about spare parts inventory, supplier terms, and procurement procedures using hybrid retrieval and CSV lookup tools.

**Overall Performance:** 75% accuracy on dev split (20 test cases)

---

## Performance Breakdown

### Answerable Questions (10 cases)
- **Accuracy:** 80% (8/10 correct, 1 partial, 1 incorrect)
- **Strengths:** Successfully queries the spares catalogue CSV and retrieves lead times, suppliers, and pricing
- **Weaknesses:** Occasional mismatches when combining data from multiple sources (CSV + markdown policies)

### Out-of-Scope Questions (5 cases)
- **Refusal Rate:** 80% (4/5 correct refusals)
- **Strengths:** Correctly identifies questions outside procurement domain
- **Weaknesses:** One case answered instead of refusing (edge case on related shipping logistics)

### Edge Cases (5 cases)
- **Accuracy:** 60% (3/5 correct, 1 partial, 1 incorrect)
- **Strengths:** Handles multi-document questions reasonably well
- **Weaknesses:** Complex aggregations across CSV and policy docs sometimes produce incomplete answers

---

## Tool Usage

**Tools Selected:** 
- `csv_lookup` - For querying spares_catalogue.csv
- `current_date` - For date-sensitive calculations

**Tool Selection Accuracy:** 95% (19/20 cases used appropriate tools)

---

## Judge Calibration

**Judge Model:** gemini-3.1-flash-lite (same as generator)  
**Calibration Accuracy:** 90.9% (10/11 gold vs corrupted pairs)

The judge correctly identified most corrupted answers but missed one case where a missing refusal should have been flagged. This indicates the judge has slight leniency toward the generator's outputs (self-preference bias).

---

## Known Limitations

1. **CSV Aggregation:** Complex multi-row aggregations (e.g., "total cost of all items from supplier X") may require multiple tool calls
2. **Multi-Document Synthesis:** Combining numerical data from CSV with policy text from markdown can produce incomplete answers
3. **Same-Model Judge:** Using the same model for generation and judging introduces potential self-preference bias (mitigated by deterministic checks)

---

## Recommendations

1. **Short-term:** Add examples of multi-document synthesis to system prompt
2. **Medium-term:** Implement separate judge model to reduce self-preference bias
3. **Long-term:** Add tool for complex CSV aggregations (beyond single-row lookups)

---

## Transparency Notes

- No false 100% accuracy claims
- Judge and generator use the same model (potential bias flagged)
- Test set is synthetic (not real user queries)
- Performance measured on 20 dev cases (small sample size)
- One optimizer iteration would likely improve edge case handling

---

## Conclusion

The Ship Spares Assistant demonstrates functional retrieval and tool use for procurement queries. The 75% accuracy is acceptable for an initial agent build (iteration 0). Primary improvement area is multi-document synthesis for complex edge cases.
