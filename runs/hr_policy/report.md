# ForgeAI Run Report — `hr_policy`

## 1. Brief & Requirements Summary
- **Original Brief:** Build an internal HR Policy Assistant for shore staff at OceanAI Shipping. The assistant must answer staff questions accurately from the HR policy documents covering annual/sick/parental leave, code of conduct and grievance timelines, travel and expense reimbursement caps, and employee stock options and equity vesting. Keep the tone professional, clear, and cite exact policy documents and sections; politely refuse anything not covered in the policies.
- **Scope:** Internal HR Policy Assistant for OceanAI Shipping shore staff, providing accurate information based strictly on provided policy documents regarding leave, conduct, and travel expenses.
- **Audience:** General shore staff employees; information provided must be consistent and applicable to all staff regardless of management status.
- **Tone:** Professional, clear, and objective, utilizing explicit citations of document titles and section headers for all responses.
- **Clarifying Questions Asked:** 5 (cap: 5)
- **Must-Answer Topics (5):** Annual, sick, and parental leave policies, Code of conduct and grievance procedures, Travel and lodging booking rules, Meal per diem and expense caps, Expense submission and audit processes
- **Must-Refuse Topics (5):** Employee stock options and equity vesting, Information not explicitly contained in the provided policy documents, Definitive resolutions for 'Edge Case' scenarios not covered in policy, Personal HR advice or subjective interpretation of policy, Workplace standards and conflict of interest (unsupported by provided documents)

## 2. Groundability Guard Findings
- **Supported:** 3 | **Partial:** 2 | **Unsupported (Demoted to Refusal):** 1
- **Warning:** Groundability Guard flagged 1 UNSUPPORTED topic(s) and moved them to must_refuse: Workplace standards and conflict of interest

| Topic | Status | Retrieval Score | Keyword Overlap | Reason |
|---|---|---:|---:|---|
| Annual, sick, and parental leave policies | **PARTIAL** | 0.625 | 1.00 | The evidence provides specific details for sick leave and mentions the existence of parental leave, but it lacks the actual policy details, duration, or eligibility criteria for annual and parental leave. |
| Code of conduct and grievance procedures | **PARTIAL** | 0.763 | 1.00 | The evidence provides a filing deadline and termination policy, but lacks the full procedural steps, investigation process, and comprehensive conduct expectations required to fully address the topic. |
| Travel and lodging booking rules | **SUPPORTED** | 0.582 | 1.00 | The retrieved evidence provides comprehensive rules for flight classes, advance booking lead times, and lodging per diem caps, which directly address the requested travel and lodging booking policies. |
| Meal per diem and expense caps | **SUPPORTED** | 0.760 | 1.00 | The retrieved evidence explicitly provides the daily meal per diem rates for both domestic ($50) and international ($75) travel, as well as the specific lodging caps. |
| Expense submission and audit processes | **SUPPORTED** | 0.673 | 0.80 | The retrieved evidence provides specific, actionable rules regarding receipt thresholds, submission deadlines, and finance payout SLAs for expense processing. |
| Workplace standards and conflict of interest | **UNSUPPORTED** | 0.815 | 1.00 | While the document title mentions 'Core Workplace Standards & Conflict of Interest', the provided snippets contain no actual content, definitions, or rules regarding conflict of interest policies. |

## 3. Final Agent Definition Summary
- **Name:** OceanAI_HR_Policy_Assistant
- **Description:** An internal HR policy assistant for OceanAI Shipping shore staff, providing accurate information on leave, conduct, and travel expenses based strictly on provided documentation.
- **Retrieval Config:** `strategy=heading-aware`, `chunk_size=600`, `overlap=80`, `top_k=5`, `hybrid_alpha=0.5`, `min_score=0.2`
- **Enabled Tools:** calculator

### Tool Selection Rationale (Included & Excluded)
| Tool | Included | Rationale |
|---|---|---|
| `csv_lookup` | NO | Excluded by deterministic post-check: no CSV/tabular files exist in the document folder. |
| `calculator` | YES | Included: brief/requirements involve arithmetic or pricing calculations (matched: amount). |
| `open_meteo` | NO | Excluded by deterministic post-check: no weather, forecast, or climate trigger found in brief or requirements. |
| `current_date` | NO | Excluded by deterministic post-check: no date-relative reasoning (today/expiry/deadline) requested in brief or requirements. |

## 4. Evaluation Set & Quality Filter Audit
- **Total Kept:** 20 (dev=11, held-out test=9)
- **By Category:** {'answerable': 10, 'out_of_scope': 5, 'edge': 5}
- **Raw Generated:** 20
- **Discarded (Duplicates):** 0
- **Discarded (Ungrounded Facts):** 0
- **Discarded (OOS Matched Docs):** 0
- **Discarded (Invalid Schema):** 0

## 5. Scorecard & Optimization Progress
- **Initial Overall Score:** 0.7100 (pass rate 55.0%)
- **Final Overall Score:** 0.7100 (pass rate 55.0%, 11/20 passed)
- **Dev vs Held-Out Test Score:** Dev = **0.7682** | Held-out Test = **0.6389** (gap = +0.1293)
- **Optimizer Stop Reason:** `early_stop_no_improvement_iter_1`

| Iteration | Failure Category | Action | Dev Before -> After | Test Before -> After | Outcome |
|---|---|---|---:|---:|---|
| 1 | `hallucination` | Patched grounding constraints + raised min_score 0.2->0.24: Added a strict hallucination p | 0.768 -> 0.709 | 0.639 -> 0.639 | REVERTED |

### Per-Category Scores (Final)
| Category | Score |
|---|---:|
| `answerable` | 0.6100 |
| `edge` | 0.6200 |
| `out_of_scope` | 1.0000 |

### Per-Failure-Type Counts (Final)
| Failure Category | Count |
|---|---:|
| `hallucination` | 8 |
| `prompt_defect` | 1 |
| `retrieval_miss` | 0 |
| `wrong_refusal` | 0 |

## 6. Judge Calibration & Cost Accounting
- **Calibration Accuracy (Gold vs Corrupted Self-Test):** **90.9%** (10/11)
  - Gold Pass Rate: 80.0% | Corrupted Catch Rate: 100.0%
- **Judge Model Note:** Judge uses gemini-3.1-flash-lite, which is the SAME model family as generator (gemini-3.1-flash-lite) — mitigated via deterministic primary checks, dual shuffled-criteria runs, and calibration testing, but residual self-preference bias cannot be fully ruled out.
- **Verbosity Warnings (>2.5x reference length):** 2
- **LLM Calls:** 162 (cache hits=116, misses=46)
- **Embed Calls:** 180 (cache hits=180)
- **Tokens Used (Uncached):** 70545 (prompt=59320, completion=11225)
- **Total Uncached Latency:** 305.19s

## 7. WHAT STILL FAILS AND WHY
### `ans_005` (test / answerable) — Failure Type: `hallucination`
- **Question:** When am I allowed to book a business class flight?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 1.00
- **Retrieved Sources:** code_of_conduct.md, leave_policy.md, travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** none | **Missed Facts:** []
- **Judge Evidence / Root Cause:** The agent failed on grounding and correctness. It hallucinated a 12-hour threshold (the policy states 8 hours) and a 10-day advance booking requirement that does not exist in the provided context.
- **Agent Answer Excerpt:** Business class flights are permitted for travel that is 12 hours or longer. For these flights, bookings must be made at least 10 days in advance. For any flights shorter than 12 hours, you are required to book economy class.  Citations: [source: travel_expense_policy.md, section:

### `ans_007` (test / answerable) — Failure Type: `hallucination`
- **Question:** Is business class travel permitted for a 9-hour flight?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 1.00
- **Retrieved Sources:** leave_policy.md, travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** none | **Missed Facts:** []
- **Judge Evidence / Root Cause:** The agent failed on grounding and correctness. It hallucinated a 12-hour policy threshold that does not exist in the provided context, which actually states that business class is permitted for flights 8 hours or longer.
- **Agent Answer Excerpt:** Business class travel is not permitted for a 9-hour flight. According to the policy, business class flights are available only for travel that is 12 hours or longer; for any flights shorter than 12 hours, economy class must be booked.  Citations: [source: travel_expense_policy.md

### `ans_010` (dev / answerable) — Failure Type: `hallucination`
- **Question:** If my flight is exactly 12 hours long, can I book business class?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 1.00
- **Retrieved Sources:** leave_policy.md, travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** none | **Missed Facts:** []
- **Judge Evidence / Root Cause:** The agent correctly concluded that a 12-hour flight qualifies for business class, but it provided incorrect information regarding the policy threshold, claiming it was 12 hours instead of the 8 hours stated in the retrieved context.
- **Agent Answer Excerpt:** Yes, you may book business class for a flight that is exactly 12 hours long. According to the company policy, business class flights are available for travel that is 12 hours or longer.  Citations: [source: travel_expense_policy.md, section-1: 1. Flight & Rail Booking Rules]

### `ans_011` (test / answerable) — Failure Type: `hallucination`
- **Question:** What happens if I try to book a business class flight for a 10-hour trip?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 1.00
- **Retrieved Sources:** leave_policy.md, travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** none | **Missed Facts:** []
- **Judge Evidence / Root Cause:** The agent failed on grounding and correctness because it hallucinated a 12-hour threshold for business class travel, whereas the provided context explicitly states that business class is permitted for travel 8 hours or longer.
- **Agent Answer Excerpt:** For a 10-hour trip, you are required to book economy class. According to the travel policy, business class flights are only available for travel that is 12 hours or longer; for any flights shorter than 12 hours, economy class must be booked.  **Citations:** [source: travel_expens

### `ans_012` (dev / answerable) — Failure Type: `hallucination`
- **Question:** Are there different booking rules for domestic versus international flights?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 1.00
- **Retrieved Sources:** travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** none | **Missed Facts:** []
- **Judge Evidence / Root Cause:** The agent provided incorrect information by hallucinating business class booking rules that were not in the source text, failing the grounding and correctness criteria.
- **Agent Answer Excerpt:** The provided policy documents do not differentiate booking rules (such as advance booking lead days or class of service) based on whether a flight is domestic or international. The booking rules apply consistently to all travel.  **Flight Booking Rules:** *   **Economy Class:** S

### `ans_013` (test / answerable) — Failure Type: `hallucination`
- **Question:** What is the minimum flight duration required to qualify for business class?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 1.00
- **Retrieved Sources:** code_of_conduct.md, leave_policy.md, travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** none | **Missed Facts:** []
- **Judge Evidence / Root Cause:** The agent failed on grounding and correctness because it hallucinated a 12-hour requirement when the provided context clearly states that business class is available for travel that is 8 hours or longer.
- **Agent Answer Excerpt:** Business class flights are available for travel that is 12 hours or longer. For any flights shorter than 12 hours, economy class must be booked.  Citations: [source: travel_expense_policy.md, section: 1. Flight & Rail Booking Rules]

### `edge_017` (test / edge) — Failure Type: `hallucination`
- **Question:** What is the total maximum reimbursement for a 2-day domestic trip including hotel and daily meal per diems?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 1.00
- **Retrieved Sources:** leave_policy.md, travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** 400 | **Missed Facts:** []
- **Judge Evidence / Root Cause:** The agent provided a correct, grounded, and well-cited answer that accurately calculated the maximum reimbursement based on the provided policy.
- **Agent Answer Excerpt:** The total maximum reimbursement for a 2-day domestic trip is $500. This total is calculated based on the domestic hotel cap of $200 per night for two nights ($400) and the daily meal per diem of $50 for two days ($100).  Citations: [source: travel_expense_policy.md, section: 2. L

### `edge_018` (dev / edge) — Failure Type: `prompt_defect`
- **Question:** Can I accept a gift?
- **Score:** 0.400 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 0.00
- **Retrieved Sources:** code_of_conduct.md, leave_policy.md (Expected: code_of_conduct.md)
- **Hallucinated Tokens:** none | **Missed Facts:** ['Gifts exceeding $50 are prohibited']
- **Judge Evidence / Root Cause:** The agent provided a complete, accurate, and well-grounded answer that adhered to all instructions and policy requirements.
- **Agent Answer Excerpt:** Employees are permitted to accept gifts, provided the value does not exceed $50 USD. Any gift or gratuity received must be reported to the Human Resources Department within 7 business days of receipt.  [source: code_of_conduct.md, section-1 | Gift Value Threshold]

### `edge_020` (dev / edge) — Failure Type: `hallucination`
- **Question:** If I drive 450 kilometers for business, what is my total mileage reimbursement?
- **Score:** 0.350 | **Expected Behavior:** `answer` | **Key-Fact Coverage:** 0.00
- **Retrieved Sources:** leave_policy.md, travel_expense_policy.md (Expected: travel_expense_policy.md)
- **Hallucinated Tokens:** 225.00 | **Missed Facts:** ['Personal vehicle rate is $0.50 per kilometer']
- **Judge Evidence / Root Cause:** The agent provided a correct, grounded, and well-cited answer that followed all instructions.
- **Agent Answer Excerpt:** Your total mileage reimbursement for 450 kilometers is $225.00.  Citations: [source: travel_expense_policy.md, section: 3. Ground Transport & Mileage]

## 8. Trust Notes & Known Limitations
- **Small-Model Capability:** Small local models (e.g. 3B parameters) can occasionally omit secondary atomic facts, misformat `<tool>` calls, or drift on multi-document synthesis.
- **Judge Self-Preference:** When `JUDGE_MODEL` equals `LLM_MODEL`, LLM-as-judge scores may share blind spots with the generator; deterministic checks (key-fact overlap, exact number matching, citation existence) act as the primary guardrail.
- **Auto-Generated Eval Bias:** Even after source-fact grounding and OOS retrieval filtering, synthetic eval questions may not reflect every messy phrasing real users use.
- **Overfitting Guard:** Optimizer decisions used only the `dev` split; the held-out `test` split measures generalization.
