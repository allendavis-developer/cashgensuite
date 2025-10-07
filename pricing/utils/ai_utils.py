import os, re
import google.generativeai as genai
from google.generativeai import GenerationConfig

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash-lite"

def call_gemini_sync(prompt: str) -> str:
    """
    Call Google Gemini 2.5 Flash Lite (synchronous) with a simple prompt string.
    Returns plain text response, or error message if failed.
    """
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)

        # I want to reduce the temperature so the recommended prices are less random
        generation_config = GenerationConfig(
            temperature=0.0,  # Lower temperature -> more deterministic
            max_output_tokens=8192  # Adjust as needed
        )

        response = model.generate_content(prompt, generation_config=generation_config)
        return response.text.strip() if response and response.text else "No response"
    except Exception as e:
        print("Gemini API error:", e)
        return "Sorry, I couldn't get a response from Gemini."


def build_bulk_price_analysis_prompt(
    item_name: str,
    description: str,
    competitor_data: str,
    cost_price: str = "",
    urgency: int = 3,
    cex_discount_percent: int = 20,
    min_margin_percent: float = 37.5
) -> str:
    """
    Constructs a specialized prompt for Gemini AI for bulk website listings on CashGenerator.
    Pricing logic:
      - Use Cash Converters listings as a reference to identify price clusters
      - Aim to be at the **top of the CashGenerator website listings** (i.e., lowest visible price)
      - Never price below a minimum margin (37.5% default)
      - CG price ≈ CeX price minus X% (default 20%)
      - Round final price up to nearest multiple of 2
      - If eBay sold price > (CeX minus X%), use eBay price instead
      - Desirable / high-demand items may ignore the 20% rule
    """

    urgency_context = {
        1: "No rush to sell - maximize margin.",
        2: "Normal sale - healthy margin while staying competitive.",
        3: "Moderate urgency - balance turnover speed with margin.",
        4: "High urgency - price to move quickly.",
        5: "Very high urgency - clearance / liquidation pricing."
    }

    urgency_text = urgency_context.get(urgency, urgency_context[3])

    prompt = f"""
You are a retail pricing assistant for **CashGenerator website listings**.

Your job is to recommend a **final selling price** based on the given data.

---
🧾 ITEM DETAILS
- Name: {item_name}
- Description: {description}
- Cost Price: {cost_price or 'N/A'}
- Sale Urgency: {urgency}/5 ({urgency_text})

---
COMPETITOR DATA (CeX, eBay, Cash Converters, etc.):
{competitor_data}

---

PRICING RULES (CASHGENERATOR WEBSITE):

1. **Top-of-Website Positioning:**  
   - Your goal is to price the item so it appears at the **top of the CashGenerator website listings**, meaning **the lowest visible price**.
   - Ensure your price is lower than the lowest price in CashGenerator.  
   - Use **Cash Converters listings only as a reference** to identify price clusters. **We are not listing items on Cash Converters.**  
   - Aim to place the CashGenerator price **slightly below the main cluster average** using **meaningful psychological steps** (e.g., if cluster ≈ £89.99, consider £79.99–£84.99) to stand out.  
   - **Do NOT price below a minimum margin of {min_margin_percent}%**, even if cluster positioning suggests a lower price.

2. **Desirability Override:**  
   - Highly desirable or high-turnover items (e.g., Nintendo Switch 2, PS5, iPhone 17, flagship Samsung or Pixel phones)  
     may be priced **closer to CeX or eBay** rather than applying the full discount.

3. **Urgency Effect:**  
   - Higher urgency → lower, faster-selling price.  
   - Lower urgency → prioritize margin while still aiming for top-of-website placement.

---

YOUR TASK:
- Recommend the **final CashGenerator website price** to achieve **top-of-website visibility** while satisfying minimum margin.  
- Keep reasoning concise (≤100 words), professional, and cite competitor prices where relevant.  
- Do **not** invent unknown model specs.  
- If data is missing (e.g., no CeX, no eBay, limited Cash Converters listings), mention it briefly.

---
OUTPUT FORMAT:
Reasoning in one concise paragraph.

Then end your answer with:
**FINAL:£SUGGESTED_PRICE**
Example: FINAL:£502
    """.strip()

    return prompt


def build_price_analysis_prompt(
    item_name: str,
    description: str,
    competitor_data: str,
    cost_price: str = "",
    market_item_title: str = "",
    urgency: int = 3,
) -> str:
    """
    Constructs the prompt for Gemini AI to suggest an ideal selling price.
    urgency: 1 (no rush) → 5 (urgent / quick sale needed)
    """

    urgency_context = {
        1: "No rush to sell — prioritize maximum profit.",
        2: "Standard timeline — balance profit and sellability.",
        3: "Moderate urgency — prefer faster turnover.",
        4: "High urgency — prioritize quick sale.",
        5: "Very urgent — must sell quickly, price aggressively."
    }

    urgency_text = urgency_context.get(urgency, urgency_context[3])

    prompt = f"""
You are an expert retail pricing analyst for **CashGenerators**, a pawn shop similar to CashConverters.

Your task is to suggest an ideal selling price for listing this item on the **CG Website**.

---

### 🧾 ITEM DETAILS
- Item Title: {item_name}
- Market Item: {market_item_title or "N/A"}
- Description: {description or "N/A"}
- Sale Urgency: {urgency}/5 → {urgency_text}

---

### 🏷️ COMPETITOR LISTINGS
{competitor_data or "No competitor data available"}

---

### 💡 INSTRUCTIONS
Analyse the competitor prices, item details, and sale urgency to produce a **single recommended selling price** for CG Website.

Follow these rules carefully:

1. **Competitor Focus**
   - ALWAYS quote relevant competitor listings (with store name and location) to justify your reasoning.  
   - Prioritise **CashGenerator** listings over other marketplaces.  
   - Ignore irrelevant listings or mismatched models.  

2. **Reasoning**
   - Write reasoning in **one single paragraph**, not bullet points.  
   - Be concise, professional, and matter-of-fact.  
   - Do **not hallucinate** missing product details (e.g., storage capacity, model version).  
   - Mention if any important details are missing that affect your ability to set a price.

3. **Urgency Impact**
   - Factor in the sale urgency:
     - High urgency (4–5): Lower, faster-selling prices.  
     - Low urgency (1–2): Higher margin pricing is acceptable.

4. **Desirability & Sellability**
   - Consider desirability (demand/popularity) and sellability (ease of sale).  
   - Use real competitor pricing context to judge this balance.

5. **Cost Price Awareness**
   - If a cost price is provided, calculate and **show the margin percentage**:  
     (selling price − cost price) ÷ selling price × 100  
   - Mention this margin and explain if it’s healthy or thin.

---

### 📘 OUTPUT FORMAT
1. Your reasoning paragraph (max 120 words).  
2. Then, on a **new line**, end with:  
   `FINAL:£SUGGESTED_PRICE`  
   Example: `FINAL:£279.99`

---

Keep your tone factual, data-driven, and confident.
Do not include markdown, quotes, or extra commentary outside the required format.
    """.strip()

    return prompt


def generate_price_analysis(item_name, description, competitor_data, cost_price="", urgency=3):
    """Generate AI analysis for pricing"""
    prompt = build_price_analysis_prompt(
        item_name=item_name,
        description=description,
        competitor_data=competitor_data,
        cost_price=cost_price,
        urgency=urgency,
    )

    ai_response = call_gemini_sync(prompt)
    reasoning, suggested_price = split_reasoning_and_price(ai_response)

    return ai_response, reasoning, suggested_price

def generate_bulk_price_analysis(item_name, description, competitor_data, cost_price="", urgency=3):
    """Generate AI-based price analysis for bulk website listing."""
    prompt = build_bulk_price_analysis_prompt(
        item_name=item_name,
        description=description,
        competitor_data=competitor_data,
        cost_price=cost_price,
        urgency=urgency,
    )

    ai_response = call_gemini_sync(prompt)
    reasoning, suggested_price = split_reasoning_and_price(ai_response)

    return ai_response, reasoning, suggested_price


def split_reasoning_and_price(ai_response: str):
    """
    Splits AI response into reasoning and FINAL:£<price>.
    If not found, returns (ai_response, "N/A")
    """
    decimal_price=None
    match = re.search(r"(.*)FINAL:\s*£\s*(\d+(?:\.\d+)?)", ai_response, re.DOTALL)
    if match:
        reasoning = match.group(1).strip()
        price = f"£{match.group(2)}"
        return reasoning, price
    return ai_response.strip(), "N/A"
