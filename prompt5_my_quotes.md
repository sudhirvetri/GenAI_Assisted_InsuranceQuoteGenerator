# My Quotes Feature — Backend + Frontend

## Context
Working GenAI Insurance Quote Generator. React 18 + Vite + Tailwind CSS.
API Base: https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1
Auth: Cognito JWT in Authorization header.

Aurora txndb tables:
- transactions: transaction_id (uuid), submission_id (uuid FK), user_id (varchar), status, created_at
- submissions: submission_id (uuid PK), user_id, age, category, family_composition, target_si, budget_premium, created_at
- plan_selections: selection_id (uuid PK), transaction_id (uuid FK), plan_id, selected_at

DynamoDB table iqg-quote-results: PK=transactionId, has recommendations JSON array and status field.

---

## CHANGE 1: New Lambda — lambda/get_my_quotes/get_my_quotes.py

Create new file at:
/workspaces/GenAI_Assisted_InsuranceQuoteGenerator/lambda/get_my_quotes/get_my_quotes.py

This Lambda handles GET /v1/my-quotes

Logic:
1. Extract user_id from event["requestContext"]["authorizer"]["userId"]

2. Query txndb for all transactions belonging to this user:
SELECT 
    t.transaction_id,
    t.status,
    t.created_at,
    s.age,
    s.category,
    s.family_composition,
    s.target_si,
    s.budget_premium,
    ps.plan_id as selected_plan_id,
    ps.selected_at
FROM transactions t
JOIN submissions s ON s.submission_id = t.submission_id
LEFT JOIN plan_selections ps ON ps.transaction_id = t.transaction_id
WHERE t.user_id = :user_id
ORDER BY t.created_at DESC
LIMIT 20

3. For each COMPLETE transaction, fetch recommendations from DynamoDB
   iqg-quote-results table using transactionId as key.
   Extract just these fields per recommendation to keep response small:
   plan_id, plan_name, annual_premium, sum_insured, tier, highlights, reason

4. Return 200:
{
  "transactions": [
    {
      "transaction_id": "...",
      "status": "COMPLETE",
      "created_at": "2026-05-31T...",
      "profile": {
        "age": 35,
        "category": "family",
        "family_composition": "self_spouse_children",
        "target_si": 1000000,
        "budget_premium": 30000
      },
      "selected_plan_id": "FAM-GLD-003",  // null if not selected yet
      "selected_at": "2026-05-31T...",     // null if not selected yet
      "recommendations": [...]             // empty array if not COMPLETE
    }
  ],
  "count": 1
}

Use the same Aurora Data API helper pattern (db_execute, rows_to_dicts, make_param, respond)
as other Lambdas. Handle errors with try/except. Return empty list if no transactions found.

Include standard CORS headers in respond() helper.

---

## CHANGE 2: CDK Stack — Add new Lambda + API route

File: /workspaces/GenAI_Assisted_InsuranceQuoteGenerator/iqg-cdk/lib/iqg-cdk-stack.ts

Add after the persistSelectionFn Lambda definition:

1. New Lambda:
   - functionName: iqg-get-my-quotes
   - handler: get_my_quotes.handler
   - code: ../lambda/get_my_quotes
   - runtime: Python 3.12
   - memory: 256MB
   - timeout: 15 seconds
   - role: lambdaRole (same shared role)
   - environment: commonEnv (same env vars)

2. New API route:
   - GET /my-quotes → iqg-get-my-quotes Lambda (WITH authorizer)

---

## CHANGE 3: Frontend — New MyQuotes page + routing logic

### New file: frontend/src/pages/MyQuotes.jsx

This page:
1. On mount, calls GET /v1/my-quotes with Authorization header
2. Shows loading spinner while fetching
3. If response has 0 transactions → redirect to /quote-form immediately
4. If response has transactions → show the My Quotes page

Page layout:
- Navbar at top
- Header: "Your Insurance Quotes" with a "Get New Quote" button (teal, top right) → navigates to /quote-form
- Cards grid (one card per transaction, most recent first)

Each transaction card shows:
- Status badge: COMPLETE (green), PENDING (yellow), FAILED (red)
- Profile summary: "Family • Age 35 • Budget ₹30,000/yr"
- Date: "Generated on May 31, 2026"
- If has selected_plan_id: show "Selected Plan: {selected_plan_id}" in a teal highlight box
  with selected_at date
- If status=COMPLETE and no selected_plan_id: show "No plan selected yet"
- Recommendations preview: show 3 small plan name badges (pill style)
  from recommendations array
- Two buttons at bottom of card:
  - "View & Select Plans" (primary teal button) → navigate to /results/{transaction_id}
  - If has selected_plan_id: also show "Change Selection" (outline button) → 
    navigate to /results/{transaction_id}

### Modify: frontend/src/pages/Callback.jsx

After successful token exchange and login(), instead of navigating directly to /quote-form:
1. Call GET /v1/my-quotes with the new token
2. If response has transactions with count > 0 → navigate to /my-quotes
3. If response has count = 0 → navigate to /quote-form
4. If fetch fails → navigate to /quote-form (fallback)

### Modify: frontend/src/App.jsx

Add new route:
import MyQuotes from './pages/MyQuotes'
Add: <Route path="/my-quotes" element={<MyQuotes />} />

---

## IMPORTANT NOTES:

1. Write get_my_quotes.py completely — no placeholders
2. For CDK changes: only show the specific lines to ADD to iqg-cdk-stack.ts,
   not the whole file. Show exact insertion point.
3. Write MyQuotes.jsx completely
4. For Callback.jsx: show only the changed section (the navigation logic after login())
5. For App.jsx: show only the 2 lines to add
6. Do NOT run any commands
7. Use same formatINR helper pattern as other pages for currency display
8. The /results/:transactionId page already works for showing recommendations
   so "View & Select Plans" just navigates there — no changes needed to Results.jsx
