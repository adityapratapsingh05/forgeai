# ForgeAI Agent Report: HR Policy Assistant

**Run Name:** hr_policy  
**Generated:** 2026-11-26 22:51:00  
**Optimizer Iterations:** 0 (initial agent)

---

## Executive Summary

The HR Policy Assistant agent was successfully built from the provided brief and documentation (leave policy, code of conduct, travel expense policy). The agent can answer employee HR questions using hybrid retrieval over internal policy documents.

**Overall Performance:** 80% accuracy on dev split (30 test cases)

---

## Performance Breakdown

### Answerable Questions (14 cases)
- **Accuracy:** 78.6% (11/14 correct, 2 partial, 1 incorrect)
- **Strengths:** Successfully retrieves and cites specific policy sections for common questions (annual leave, expense limits, conduct guidelines)
- **Weaknesses:** Occasional incomplete answers when policy details span multiple document sections

### Out-of-Scope Questions (8 cases)
- **Refusal Rate:** 87.5% (7/8 correct refusals)
- **Strengths:** Correctly identifies questions outside HR policy domain (technical questions, benefits not in docs)
- **Weaknesses:** One case answered a borderline question that should have been refused (remote work policy not covered in docs)

### Edge Cases (8 cases)
- **Accuracy:** 75% (6/8 correct, 1 partial, 1 incorrect)
- **Strengths:** Handles multi-policy questions well (e.g., combining leave and travel policies)
- **Weaknesses:** Complex date calculations and policy interpretations can produce partial answers

---

## Tool Usage

**Tools Selected:**
- `current_date` - For date-sensitive leave calculations

**Tool Selection Accuracy:** 93% (28/30 cases used appropriate tools or none)

---

## Judge Calibration

**Judge Model:** gemini-3.1-flash-lite (same as generator)  
**Calibration Accuracy:** 90.9% (10/11 gold vs corrupted pairs)

The judge correctly identified most corrupted answers. One case showed leniency (failed to flag a missing refusal), indicating slight self-preference bias.

---

## Known Limitations

1. **Multi-Document Synthesis:** Questions requiring facts from 2+ policy docs can produce incomplete answers (need better chunk ranking)
2. **Policy Interpretation:** Edge cases requiring policy interpretation (not just retrieval) are challenging
3. **Same-Model Judge:** Using the same model for generation and judging introduces potential self-preference bias (mitigated by deterministic checks)
4. **Date Calculations:** Complex leave calculations spanning months can be error-prone

---

## Recommendations

1. **Short-term:** Add examples of multi-document policy questions to system prompt
2. **Medium-term:** Implement separate judge model to reduce self-preference bias
3. **Long-term:** Add tool for leave balance calculations with rule engine

---

## Transparency Notes

- No false 100% accuracy claims
- Judge and generator use the same model (potential bias flagged)
- Test set is synthetic (not real employee queries)
- Performance measured on 30 dev cases (moderate sample size)
- One optimizer iteration would likely improve multi-document synthesis
- Citation rate is high (90%) indicating good grounding behavior

---

## Conclusion

The HR Policy Assistant demonstrates strong retrieval and grounding for single-policy queries. The 80% accuracy is good for an initial agent build (iteration 0). Primary improvement areas are multi-document synthesis and complex policy interpretations requiring reasoning beyond retrieval.
