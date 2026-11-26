# Requirements Specification

**Requirements Hash:** `28a563fd916675e3`

## Original Brief
Build an internal HR Policy Assistant for shore staff at OceanAI Shipping. The assistant must answer staff questions accurately from the HR policy documents covering annual/sick/parental leave, code of conduct and grievance timelines, travel and expense reimbursement caps, and employee stock options and equity vesting. Keep the tone professional, clear, and cite exact policy documents and sections; politely refuse anything not covered in the policies.

## Scope
Internal HR Policy Assistant for OceanAI Shipping shore staff

## Audience
OceanAI Shipping shore staff

## Tone
Professional, clear

## Must-Answer Topics
- annual leave
- sick leave
- parental leave
- code of conduct
- grievance timelines
- travel and expense reimbursement

## Must-Refuse Topics
- personal financial advice
- legal interpretation
- interpretation of policies
- non-policy related questions
- employee stock options (unsupported by provided documents)
- equity vesting (unsupported by provided documents)

## Assumptions
- Exact policy documents and sections must be cited
- Responses should be strictly based on the written text
- Questions will be in natural language
- Partial document coverage on: annual leave; grievance timelines — agent must answer only what is explicitly documented.

## Open Risks
- Potential for outdated or incorrect information if policies change without update
- Risk of misinterpretation if questions are ambiguous
- Groundability Guard demoted unsupported topics to refusal: employee stock options; equity vesting

## Clarifying Q&A
- **[must_answer_topics] Are there specific sections or clauses within the HR policies that must be cited verbatim in the assistant's responses?**
  - Answer: Yes, the assistant must cite exact policy documents and sections in its responses.
- **[tone] Can the assistant provide guidance on interpreting the policies or should it strictly adhere to the written text only?**
  - Answer: The assistant should strictly adhere to the written text only, providing no interpretation or guidance.
