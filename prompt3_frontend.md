# Frontend Implementation

Build a complete React 18 + Vite + Tailwind CSS SPA for the SwiftCare Insurance Quote Generator.

## Configuration
- API Base URL: https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1
- Cognito User Pool ID: us-east-1_dVaDd5mr8
- Cognito Client ID: 56ilueodgm4jmccvb5l9bjj47l
- Cognito Domain: https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com
- Region: us-east-1

## Project Setup
Create in /workspaces/GenAI_Assisted_InsuranceQuoteGenerator/frontend/
Use Vite + React + Tailwind CSS.
Do NOT use AWS Amplify — use plain fetch() with JWT tokens directly.
Store JWT token in memory (useState) only — no localStorage.

## Authentication Flow
- Use Cognito Hosted UI for sign-in
- Redirect URL: http://localhost:5173/callback
- After sign-in, Cognito redirects to /callback with ?code=xxx
- Exchange code for tokens using fetch POST to:
  https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com/oauth2/token
  with grant_type=authorization_code, code, redirect_uri, client_id
- Store id_token in React state
- Pass as Authorization: Bearer {token} on all API calls

## Pages / Components

### 1. Landing Page (/)
- Clean professional insurance company look
- SwiftCare Health Insurance branding (teal/blue color scheme)
- Hero section: "Get Your Personalized Health Insurance Quote in Seconds"
- Subheading: "AI-powered recommendations tailored to your needs"
- Single CTA button: "Get My Quote" → redirects to Cognito Hosted UI
- Cognito sign-in URL format:
  https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com/login
  ?client_id=56ilueodgm4jmccvb5l9bjj47l
  &response_type=code
  &scope=email+openid+profile
  &redirect_uri=http://localhost:5173/callback

### 2. Callback Page (/callback)
- Shows "Signing you in..." spinner
- Extracts ?code from URL params
- Exchanges code for token via POST to Cognito /oauth2/token
- On success: stores token in state, redirects to /quote-form
- On error: shows error message with retry button

### 3. Quote Form Page (/quote-form)
Clean form with these fields:

Section "About You":
- Category (radio buttons): Individual / Family / Senior Citizen
- Age (number input): 18-99
- Family Composition (dropdown):
  Options: self, self_spouse, self_spouse_children, 
           self_parents, self_spouse_children_parents
  Only show if category = family
- Email (text input)

Section "Coverage Preferences":
- Target Sum Insured (dropdown):
  ₹3,00,000 / ₹5,00,000 / ₹7,50,000 / ₹10,00,000 / 
  ₹15,00,000 / ₹20,00,000 / ₹30,00,000 / ₹50,00,000
- Annual Budget for Premium (dropdown):
  Up to ₹10,000 / ₹15,000 / ₹20,000 / ₹25,000 / 
  ₹30,000 / ₹50,000 / ₹1,00,000+
- Lifestyle Priorities (checkboxes, can select multiple):
  Maternity Cover / Annual Health Checkup / Teleconsultation /
  Critical Illness Cover / AYUSH Treatment / Daycare Procedures /
  Ambulance Cover / Restoration Benefit
- Pre-existing Conditions (checkboxes):
  Diabetes / Hypertension / Heart Disease / Asthma / None

Section "Consent":
- Checkbox: "I acknowledge the IRDAI disclosure and consent to 
  processing my health information for insurance quote generation"
- Must be checked to submit

Submit button: "Generate My Quote"
- Calls POST /quotes/submit with Authorization header
- On success: redirect to /results/{transaction_id}

### 4. Results Page (/results/:transactionId)

Loading state (while status=PENDING):
- Animated spinner with SwiftCare logo
- "Our AI is analyzing 30+ plans to find your best matches..."
- Poll GET /quotes/{transactionId} every 2 seconds
- Show elapsed time counter

Results state (when status=COMPLETE):
- Header: "Your Personalized Recommendations"
- Subheader: "Based on your profile, our AI recommends these top 3 plans"

3 Plan Cards (side by side on desktop, stacked on mobile):
Each card shows:
- Plan name (large)
- Tier badge (Silver/Gold/Platinum with color coding:
  Silver=gray, Gold=yellow/amber, Platinum=purple)
- Annual Premium (large, prominent): ₹XX,XXX/year
- Sum Insured: ₹XX,XX,XXX
- Co-payment: X% (or "Zero Co-pay" if 0)
- PED Waiting: X months
- Key highlights (bullet list, max 3)
- AI Reason (italic, 2-3 sentences from recommendations[].reason)
- "Select This Plan" button

Chat Panel (below the cards):
- Title: "Have questions about your recommendations?"
- Chat message history (scrollable)
- Text input: "Ask about your plans..."
- Send button
- On send: POST /chat with transaction_id and message
- Display response in chat bubble format
- Show loading indicator while waiting

### 5. Selection Confirmation (/confirmed)
- Shows after user clicks "Select This Plan"
- Calls POST /selections with transaction_id and plan_id
- Display: "You've selected [Plan Name]"
- Summary of selected plan benefits
- "Start Over" button → back to landing

## Technical Requirements
- React Router v6 for routing
- No Redux — use useState/useContext only
- Token stored in React Context (AuthContext) accessible across pages
- All API calls use fetch() with Authorization header
- Handle loading states on every async operation
- Handle errors gracefully — show user-friendly messages
- Mobile responsive (Tailwind responsive classes)

## File Structure
frontend/
  src/
    main.jsx
    App.jsx
    context/
      AuthContext.jsx      ← stores token, userId
    pages/
      Landing.jsx
      Callback.jsx
      QuoteForm.jsx
      Results.jsx
      Confirmed.jsx
    components/
      PlanCard.jsx
      ChatPanel.jsx
      LoadingSpinner.jsx
      Navbar.jsx
  index.html
  vite.config.js
  tailwind.config.js
  package.json

## Color Scheme
Primary: teal-600 (#0d9488)
Secondary: blue-600 (#2563eb)  
Gold tier: amber-400
Silver tier: gray-400
Platinum tier: purple-500
Background: gray-50
Cards: white with shadow

Write ALL files completely. Start with package.json, 
then vite.config.js, tailwind.config.js, index.html, 
then all src/ files.
