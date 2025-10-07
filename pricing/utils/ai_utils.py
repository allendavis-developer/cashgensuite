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
            max_output_tokens=1024  # Adjust as needed
        )

        response = model.generate_content(prompt, generation_config=generation_config)
        return response.text.strip() if response and response.text else "No response"
    except Exception as e:
        print("Gemini API error:", e)
        return "Sorry, I couldn't get a response from Gemini."


def build_price_analysis_prompt(
        item_name: str,
        description: str,
        competitor_data: str,
        cost_price: str = "",
        market_item_title: str = "",
        urgency: int = 3  # Add this parameter with default value
) -> str:
    """
    Constructs the prompt for Gemini AI to suggest an ideal selling price.
    urgency: 1 (no rush) to 5 (urgent/quick sale needed)
    """

    urgency_context = {
        1: "No rush to sell - prioritize maximum profit",
        2: "Standard timeline - balance profit and sellability",
        3: "Moderate urgency - prefer faster turnover",
        4: "High urgency - prioritize quick sale",
        5: "Very urgent - must sell quickly, price aggressively"
    }

    urgency_text = urgency_context.get(urgency, urgency_context[3])

    prompt = (
        f"Item Title: {item_name}\n"
        f"Market Item: {market_item_title}\n"
        f"Description: {description}\n\n"
        f"Sale Urgency: {urgency}/5 - {urgency_text}\n\n"  # Add this line
        f"Competitor Listings:\n{competitor_data}\n\n"
         "Pricing Rules:\n"
        "CG (CashGenerators) is a pawn shop in a similar vein to CashConverters."
        "Based on the competitor prices, item details, and sale urgency, suggest an ideal selling price for listing on the CG Website. "
        "Be concise, professional and matter-of-fact. "
        "Do not split your reasoning into sections. Have it as one paragraph."
        "ALWAYS quote competitor data (with the competitor name, store location) to justify reasoning. "
        "Prioritise CashGenerator listings over other listings. "
        "Please ignore data from stores which have no listings that match the exact model and do not mention them in your reasonings."
        "Consider the desirability of the item (how much people want it) and the "
        "sellability of the item (how easy it is to sell to a general population). "
        # Add urgency guidance
        "IMPORTANT: Factor in the sale urgency level when suggesting price. "
        "Higher urgency (4-5) should result in more competitive/lower prices for faster turnover. "
        "Lower urgency (1-2) allows for higher profit margins. "
        "For example, the newest Mac laptop is very desirable, but due to its price, not very "
        "sellable, although there will be a niche that will buy it. "
        "Do not hallucinate product descriptions that aren't there. As of now, you only have the item name"
        "Mention details that make it hard for you to suggest a price. For example, not knowing the storage capacity of whatever item you're trying to suggest " \
        "a price for, or not knowing what version of the item it is."
        f"ALWAYS mention this cost price in your answer if it isn't empty: {cost_price}\n\n"
        "ALWAYS end the message with FINAL:£SUGGESTED_PRICE where SUGGESTED_PRICE is the final price."
        "If given a cost price, calculate the margin AS A PERCENTAGE (show your working) with your suggested price and the cost price and mention it."
    )

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
