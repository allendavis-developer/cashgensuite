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
        token_count = model.count_tokens(prompt)
        print(f"Input tokens: {token_count}")

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
    cex_discount_percent: int = 20  # configurable (20% default)
) -> str:
    """
    Constructs a specialized prompt for Gemini AI for bulk website listings.
    Pricing logic:
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
You are a retail pricing assistant for **CashGenerators' website listings**.

Your job is to recommend a **final selling price** based on the given data.

---
🧾 ITEM DETAILS
- Name: {item_name}
- Description: {description}
- Cost Price: {cost_price or 'N/A'}
- Sale Urgency: {urgency}/5 ({urgency_text})

---
COMPETITOR DATA:
{competitor_data}

---

PRICING RULES (CG WEBSITE):

1. **CeX Benchmark Rule:**  
   - Start from the CeX selling price (if available).  
   - CG website price should be **{cex_discount_percent}% below CeX’s selling price**.  
   - Example: if CeX = £630 and rule = 20%, CG target = £504.
   - If it is not clear what condition the item is in, assume it is B.
   
2. **Rounding Rule:**  
   - Round the final price **up** to the nearest multiple of 2.  
   - Example: £503 → £504, £537 → £538.

3. **eBay Comparison Rule:**  
   - If the average of **completed eBay sold listings** is higher than (CeX minus {cex_discount_percent}%),  
     then **use the eBay average** instead.

4. **Desirability Override:**  
   - Highly desirable or high-turnover items (e.g., Nintendo Switch 2, PS5, iPhone 17, new Samsung or Pixel phones)  
     should **not** be reduced by the full {cex_discount_percent}% — price them closer to CeX or eBay.

5. **Profit Awareness:**  
   - If a cost price is provided, calculate the gross margin percentage  
     = (selling price − cost price) / selling price × 100,  
     and mention it in reasoning.

6. **Urgency Effect:**  
   - Higher urgency → lean toward lower, faster-selling prices.  
   - Lower urgency → prioritize margin and profitability.

---

YOUR TASK:
- Use the above logic and competitor data to pick the best final selling price for CG Website.  
- Keep reasoning short (≤100 words), matter-of-fact, and professional.  
- Quote key competitor prices to justify your reasoning.  
- Do **not** invent unknown model specs.  
- If data is missing (e.g., no CeX or no eBay sold listings), mention it briefly.

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
- Cost Price: {cost_price or "Not provided"}

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
