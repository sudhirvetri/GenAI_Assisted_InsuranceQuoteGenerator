# UI Improvements — 3 changes needed

## Context
Working GenAI Insurance Quote Generator app. React 18 + Vite + Tailwind CSS frontend.
API returns recommendations with these fields per plan:
plan_id, plan_name, annual_premium, sum_insured, reason, highlights, co_payment_pct, ped_waiting_months

We need to enrich recommendations with full plan details from the database.

---

## CHANGE 1: quote_worker.py — Enrich recommendations with full plan details

File: /workspaces/GenAI_Assisted_InsuranceQuoteGenerator/lambda/quote_worker/quote_worker.py

After line ~332 where recommendations are parsed from Bedrock, add a function
that looks up the full plan details from plandb for each recommended plan_id
and merges them into the recommendation object.

Add this function after the existing db_execute helper:

```python
def enrich_recommendations(recommendations, plans_map):
    """Merge full plan DB fields into each Bedrock recommendation."""
    enriched = []
    for rec in recommendations:
        plan_id = rec.get("plan_id", "")
        full_plan = plans_map.get(plan_id, {})
        merged = {
            # Bedrock fields
            "plan_id": plan_id,
            "plan_name": rec.get("plan_name", full_plan.get("plan_name", "")),
            "annual_premium": rec.get("annual_premium", full_plan.get("annual_premium_base", 0)),
            "sum_insured": rec.get("sum_insured", full_plan.get("sum_insured", 0)),
            "reason": rec.get("reason", ""),
            "highlights": rec.get("highlights", []),
            # Full plan fields from DB
            "tier": full_plan.get("tier", ""),
            "category": full_plan.get("category", ""),
            "co_payment_pct": full_plan.get("co_payment_pct", rec.get("co_payment_pct", 0)),
            "room_rent_limit": full_plan.get("room_rent_limit", ""),
            "ped_waiting_months": full_plan.get("ped_waiting_months", rec.get("ped_waiting_months", 0)),
            "initial_waiting_days": full_plan.get("initial_waiting_days", 30),
            "no_claim_bonus_pct": full_plan.get("no_claim_bonus_pct", 0),
            "max_ncb_pct": full_plan.get("max_ncb_pct", 0),
            "restoration_benefit": full_plan.get("restoration_benefit", False),
            "daycare_covered": full_plan.get("daycare_covered", False),
            "ambulance_cover": full_plan.get("ambulance_cover", 0),
            "ayush_covered": full_plan.get("ayush_covered", False),
            "maternity_covered": full_plan.get("maternity_covered", False),
            "annual_checkup": full_plan.get("annual_checkup", False),
            "network_hospitals": full_plan.get("network_hospitals", 0),
            "critical_illness_cover": full_plan.get("critical_illness_cover", False),
            "teleconsult": full_plan.get("teleconsult", False),
            "policy_tenure_options": full_plan.get("policy_tenure_options", "1/2/3"),
            "renewability": full_plan.get("renewability", "Lifelong"),
            "key_exclusions": full_plan.get("key_exclusions", ""),
            "best_for": full_plan.get("best_for", ""),
        }
        enriched.append(merged)
    return enriched
```

Then find where recommendations are saved to DynamoDB (around line 350 where
"recommendations": recommendations appears) and before that line:
1. Build plans_map: a dict of plan_id -> plan row dict from the already-fetched plans list
2. Call enriched_recommendations = enrich_recommendations(recommendations, plans_map)
3. Save enriched_recommendations instead of recommendations

The plans list is already fetched earlier in the function as rows_to_dicts result.
Build the map like: plans_map = {p["plan_id"]: p for p in plans}

---

## CHANGE 2: PlanCard.jsx — Expandable full details section

File: /workspaces/GenAI_Assisted_InsuranceQuoteGenerator/frontend/src/components/PlanCard.jsx

Replace the entire file with an improved version that:

1. Keeps the existing card header (plan name, tier badge, premium, sum insured)
2. Shows co_payment_pct correctly: 0 → "Zero Co-pay", otherwise "X%"
3. Shows ped_waiting_months correctly: "X months"
4. Adds an expandable "View Plan Details" toggle button below the highlights
5. When expanded, shows a clean grid of ALL these fields:

Coverage Details section:
- Room Rent Limit: plan.room_rent_limit
- Initial Waiting Period: plan.initial_waiting_days + " days"
- Network Hospitals: plan.network_hospitals.toLocaleString()
- Policy Tenure: plan.policy_tenure_options
- Renewability: plan.renewability

Benefits section (show as ✅/❌ icons):
- Restoration Benefit: plan.restoration_benefit
- Daycare Procedures: plan.daycare_covered
- Maternity Cover: plan.maternity_covered
- Critical Illness Cover: plan.critical_illness_cover
- Teleconsultation: plan.teleconsult
- AYUSH Treatment: plan.ayush_covered
- Annual Health Checkup: plan.annual_checkup
- Ambulance Cover: ₹plan.ambulance_cover

NCB section:
- No Claim Bonus: plan.no_claim_bonus_pct + "% per year"
- Maximum NCB: plan.max_ncb_pct + "%"

Key Exclusions (if present):
- Show plan.key_exclusions as comma-separated tags

6. The "View Plan Details" / "Hide Details" toggle uses a smooth CSS transition
7. Keep the "Select This Plan" button at the bottom
8. Keep the AI Recommendation section

Use Tailwind classes only. The expand/collapse uses useState.

---

## CHANGE 3: ChatPanel.jsx — Render markdown in chat responses

File: /workspaces/GenAI_Assisted_InsuranceQuoteGenerator/frontend/src/components/ChatPanel.jsx

The AI returns markdown (## headers, **bold**, bullet points, tables).
Currently it renders as raw text. Improve the rendering:

1. Do NOT add any npm packages. Use pure React/CSS to handle the most common patterns.

2. Add a simple renderMarkdown function that converts:
   - **text** → <strong>text</strong>
   - ## Heading → <h3 className="font-bold text-gray-900 mt-3 mb-1">Heading</h3>
   - ### Heading → <h4 className="font-semibold text-gray-800 mt-2 mb-1">Heading</h4>
   - Lines starting with - or * → render as <li> items inside a <ul>
   - Lines starting with | → render as a simple HTML table with Tailwind styling
   - \n\n → paragraph break <div className="mb-2">
   - Emoji lines → render as-is (they're unicode, no special handling needed)

3. Apply this rendering only to assistant messages, not user messages.

4. The chat bubble for assistant messages should have a white background
   with a subtle border, slightly wider than user bubbles.

5. User messages stay as plain text in a teal background bubble.

6. Add a typing indicator (animated dots) while waiting for the response.

---

## Implementation notes:
- Write all 3 files completely
- For PlanCard.jsx and ChatPanel.jsx: write the complete file, not just the changes
- For quote_worker.py: only show the specific additions/changes, not the whole file
  (it's long — just show what to add and exactly where)
- Do NOT change any other files
- Do NOT run any commands
