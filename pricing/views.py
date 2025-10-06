from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Q, Prefetch
from django.utils import timezone

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from pricing.models import InventoryItem, MarketItem, CompetitorListing, PriceAnalysis, Category, MarginRule, GlobalMarginRule
from datetime import datetime

import google.generativeai as genai
from google.generativeai import GenerationConfig
import os, requests, json, re, subprocess

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
    market_item_title: str = ""
) -> str:
    """
    Constructs the prompt for Gemini AI to suggest an ideal selling price.
    """

    prompt = (
        f"Item Title: {item_name}\n"
        f"Market Item: {market_item_title}\n"
        f"Description: {description}\n\n"
        f"Competitor Listings:\n{competitor_data}\n\n"
        f"Please mention this cost price in your answer: {cost_price}\n\n"
        "Based on the competitor prices and item details, suggest an ideal selling price. "
        "Be concise, professional and matter-of-fact. "
        "Do not split your reasoning into sections. Have it as one paragraph."
        "ALWAYS quote competitor data (with the competitor name, store location) to justify reasoning. "
        "Prioritise CashGenerator listings over other listings. "
        "Please ignore data from stores which have no listings that match the exact model and do not mention them in your reasonings."
        "Consider the desirability of the item (how much people want it) and the "
        "sellability of the item (how easy it is to sell to a general population). "
        "For example, the newest Mac laptop is very desirable, but due to its price, not very "
        "sellable, although there will be a niche that will buy it. "
        "Do not hallucinate product descriptions that aren't there. As of now, you only have the item name"
        "Mention details that make it hard for you to suggest a price. For example, not knowing the storage capacity of whatever item you're trying to suggest " \
        "a price for, or not knowing what version of the item it is."
        "ALWAYS end the message with FINAL:£SUGGESTED_PRICE where SUGGESTED_PRICE is the final price."
    )
    return prompt


def get_competitor_data(item_title: str, include_url: bool = True) -> str:
    """
    Return a newline-separated string of competitor lines:
    "Competitor | Listing Title | £price | Store Name"
    If include_url=True, append the URL at the end.
    """
    if not item_title:
        return ""

    listings = CompetitorListing.objects.filter(market_item__title__icontains=item_title)
    lines = []
    for l in listings:
        price_str = f"£{l.price:.2f}" if l.price is not None else "N/A"
        store_str = l.store_name if l.store_name else "N/A"
        if include_url:
            url_str = l.url if l.url else "#"
            lines.append(f"{l.competitor} | {l.title} | {price_str} | {store_str} | {url_str}")
        else:
            lines.append(f"{l.competitor} | {l.title} | {price_str} | {store_str}")
    return "\n".join(lines)


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


def get_prefilled_data(request):
    """Extract prefilled data from request parameters"""
    return {
        'item': request.GET.get('item', ''),
        'market_item': request.GET.get('market_item', ''),
        'description': request.GET.get('description', ''),
        'serial': request.GET.get('serial', ''),
    }


def handle_item_analysis_request(request):
    """Handle JSON POST request for item analysis"""
    try:
        data = json.loads(request.body)
        return process_item_analysis(data)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def process_item_analysis(data):
    """Main processing logic for item analysis that can be reused across screens"""
    # Extract and clean data
    item_name = (data.get("item_name") or "").strip()
    description = (data.get("description") or "").strip()
    
    # Check if frontend already sent local scrape data
    local_scrape_data = data.get("local_scrape_data")

    if local_scrape_data:
        print("Using local scraper data from browser")

        # Update DB directly from local_scrape_data
        if isinstance(local_scrape_data, list):
            from pricing.models import MarketItem, CompetitorListing

            # Get or create the MarketItem
            market_item, _ = MarketItem.objects.get_or_create(
                title__iexact=item_name, defaults={"title": item_name}
            )

             # OPTIMIZED: Bulk operations instead of loop
            # First, delete existing listings for this market_item to avoid duplicates
            CompetitorListing.objects.filter(market_item=market_item).delete()

            # Prepare all listings for bulk creation
            listings_to_create = []
            for entry in local_scrape_data:
                listings_to_create.append(
                    CompetitorListing(
                        market_item=market_item,
                        competitor=entry.get("competitor", "Unknown"),
                        title=entry.get("title", "Untitled"),
                        price=entry.get("price", 0.0),
                        store_name=entry.get("store_name") or "N/A",
                        url=entry.get("url", "#")
                    )
                )

            # Single database hit for all listings
            CompetitorListing.objects.bulk_create(listings_to_create, ignore_conflicts=True)

            competitor_data_for_ai, competitor_data_for_frontend = get_or_scrape_competitor_data(item_name)
    
    # Generate AI analysis
    ai_response, reasoning, suggested_price = generate_price_analysis(
        item_name, description, competitor_data_for_ai
    )
    
    # Save analysis to database
    analysis_result = save_analysis_to_db(
        item_name, description, reasoning, suggested_price, competitor_data_for_frontend
    )
    
    # Prepare response
    return JsonResponse({
        "success": True,
        "suggested_price": suggested_price,
        "reasoning": reasoning,
        "full_response": ai_response,
        "submitted_data": {"item_name": item_name, "description": description},
        "competitor_data": competitor_data_for_frontend,
        "competitor_count": analysis_result["competitor_count"],
        "analysis_id": analysis_result["analysis_id"]  # Useful for other screens
    })


def get_or_scrape_competitor_data(item_name):
    """Get competitor data, scraping if necessary"""
    competitor_data_for_ai = get_competitor_data(item_name, include_url=False)
    competitor_data_for_frontend = get_competitor_data(item_name, include_url=True)
    
    # If no competitor data exists, trigger scraping
    if not competitor_data_for_ai.strip():
        print(f"No competitor listings found for '{item_name}'")
        
        # Re-fetch after scraping
        competitor_data_for_ai = get_competitor_data(item_name, include_url=False)
        competitor_data_for_frontend = get_competitor_data(item_name, include_url=True)
    
    return competitor_data_for_ai, competitor_data_for_frontend


def generate_price_analysis(item_name, description, competitor_data):
    """Generate AI analysis for pricing"""
    prompt = build_price_analysis_prompt(
        item_name=item_name,
        description=description,
        competitor_data=competitor_data,
    )
    
    ai_response = call_gemini_sync(prompt)
    reasoning, suggested_price = split_reasoning_and_price(ai_response)
    
    return ai_response, reasoning, suggested_price


def save_analysis_to_db(item_name, description, reasoning, suggested_price, competitor_data):
    """Save analysis results to database"""
    # Parse price from AI response
    decimal_price = parse_price_from_response(suggested_price)
    
    # Get or create inventory item
    inventory_item, _ = InventoryItem.objects.get_or_create(
        title=item_name,
        defaults={"description": description}
    )
    
    # Calculate competitor count
    competitor_count = calculate_competitor_count(competitor_data)
    
    # Save analysis
    analysis, created = PriceAnalysis.objects.update_or_create(
        item=inventory_item,
        defaults={
            "reasoning": reasoning,
            "suggested_price": decimal_price,
            "confidence": calculate_confidence(competitor_count),
            "created_at": timezone.now()
        }
    )
    
    return {
        "competitor_count": competitor_count,
        "analysis_id": analysis.id
    }


def parse_price_from_response(price_response):
    """Extract decimal price from AI response"""
    match = re.search(r"(.*)FINAL:\s*£\s*(\d+(?:\.\d+)?)", price_response, re.DOTALL)
    if match:
        price_str = match.group(2)
        return float(price_str)
    # Fallback: try to extract any number if the pattern doesn't match
    match_fallback = re.search(r"£?\s*(\d+(?:\.\d+)?)", price_response)
    if match_fallback:
        return float(match_fallback.group(1))
    return 0.0  # Default fallback


def calculate_competitor_count(competitor_data):
    """Calculate number of competitors from competitor data"""
    if not competitor_data.strip():
        return 0
    return len(competitor_data.strip().split("\n"))


def calculate_confidence(competitor_count):
    """Calculate confidence score based on competitor count"""
    return min(100, competitor_count * 15)


@require_GET
def marketitem_suggestions(request):
    query = request.GET.get("q", "").strip()
    suggestions = []

    if query:
        market_items = MarketItem.objects.filter(title__icontains=query)[:10]
        suggestions = [item.title for item in market_items]

    return JsonResponse({
        "suggestions": suggestions,
        "query": query,
        "count": len(suggestions),
    })


@csrf_exempt
@require_POST
def link_inventory_to_marketitem(request):
    try:
        data = json.loads(request.body)
        inventory_title = (data.get('inventory_title') or '').strip()
        marketitem_title = (data.get('marketitem_title') or '').strip()
        exclude_keywords = (data.get('exclude_keywords') or '').strip()  # optional

        if not inventory_title:
            return JsonResponse({'success': False, 'error': 'Missing inventory title'})
        if not marketitem_title:
            return JsonResponse({'success': False, 'error': 'Missing market item title'})

        inventory_item, inventory_created = InventoryItem.objects.get_or_create(
            title__iexact=inventory_title,
            defaults={'title': inventory_title}  # optional fields
        )

        # Check if MarketItem exists
        market_item, marketitem_created = MarketItem.objects.get_or_create(
            title__iexact=marketitem_title,
            defaults={'title': marketitem_title, 'exclude_keywords': exclude_keywords}
        )

        competitor_count = market_item.listings.count()


        # Link the inventory item
        inventory_item.market_item = market_item
        inventory_item.save()

        return JsonResponse({
            'success': True,
            'competitor_count': competitor_count,
            'linked_inventory': inventory_item.title,
            'linked_market_item': market_item.title,
            'created_new_marketitem': marketitem_created  # True if a new MarketItem was created
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
def unlink_inventory_from_marketitem(request):
    try:
        data = json.loads(request.body.decode('utf-8') if isinstance(request.body, bytes) else request.body)
        inventory_title = (data.get('inventory_title') or '').strip()
        marketitem_title = (data.get('marketitem_title') or '').strip()

        if not inventory_title:
            return JsonResponse({'success': False, 'error': 'Missing inventory_title'}, status=400)

        try:
            inventory_item = InventoryItem.objects.get(title__iexact=inventory_title)
        except InventoryItem.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Inventory item not found'}, status=404)

        if not inventory_item.market_item:
            return JsonResponse({'success': False, 'error': 'Inventory item is not linked'}, status=400)

        if marketitem_title and inventory_item.market_item.title.lower() != marketitem_title.lower():
            return JsonResponse({'success': False, 'error': 'Inventory item is linked to a different MarketItem'}, status=400)

        inventory_item.market_item = None
        inventory_item.save()

        return JsonResponse({'success': True})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)



def scrape_all_competitors(item_name: str):
    """
    Run the scraper for all configured competitors and save results to DB.
    """
    try:
        print(f"Scraping all competitors for '{item_name}'...")
        save_prices(COMPETITORS, item_name)  # pass list, not single
    except Exception as e:
        print(f"⚠️ Scraper failed for {item_name}: {e}")


@csrf_exempt
@require_POST
def update_marketitem_keywords(request):
    try:
        data = json.loads(request.body)
        marketitem_title = (data.get("marketitem_title") or "").strip()
        exclude_keywords = (data.get("exclude_keywords") or "").strip()

        if not marketitem_title:
            return JsonResponse({"success": False, "error": "Missing MarketItem title"}, status=400)

        market_item = MarketItem.objects.get(title__iexact=marketitem_title)
        market_item.exclude_keywords = exclude_keywords
        market_item.save()

        return JsonResponse({"success": True, "message": "Keywords updated successfully"})
    except MarketItem.DoesNotExist:
        return JsonResponse({"success": False, "error": "MarketItem not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def bulk_analysis(request):
    return render(request, 'analysis/bulk_analysis.html')


@csrf_exempt
@require_POST
def bulk_analyse_items(request):
    """
        Analyse multiple items in bulk, using local scrape data if available.
        """
    try:
        data = json.loads(request.body)
        items = data.get("items", [])
        local_scrape_data = data.get("local_scrape_data", [])

        if not items:
            return JsonResponse({"success": False, "error": "No items provided"})

        # Map scraped data by barcode for easier lookup
        scrape_lookup = {
            entry.get("barcode"): entry for entry in local_scrape_data or []
        }

        results = []

        for item_data in items:
            barcode = item_data.get("barcode", "")
            item_name = (item_data.get("name") or "").strip()
            description = (item_data.get("description") or "").strip()
            market_item_title = (item_data.get("market_item") or "").strip()
            cost_price = item_data.get("cost_price", "").strip()

            # Skip invalid entries
            if not item_name:
                results.append({
                    "barcode": barcode,
                    "success": False,
                    "error": "Missing item name"
                })
                continue

            # Get scraped competitor data from the lookup
            scraped_entry = scrape_lookup.get(barcode)
            local_listings = (
                scraped_entry.get("competitor_data", [])
                if scraped_entry and scraped_entry.get("success") else []
            )

            if local_listings:
                print(f"Using local scrape data for {item_name}")

                # Save listings to DB
                market_item, _ = MarketItem.objects.get_or_create(
                    title__iexact=item_name, defaults={"title": item_name}
                )
                CompetitorListing.objects.filter(market_item=market_item).delete()

                CompetitorListing.objects.bulk_create([
                    CompetitorListing(
                        market_item=market_item,
                        competitor=l.get("competitor", "Unknown"),
                        title=l.get("title", "Untitled"),
                        price=l.get("price", 0.0),
                        store_name=l.get("store_name") or "N/A",
                        url=l.get("url", "#")
                    ) for l in local_listings
                ])
            else:
                print(f"⚠️ No local data found for {item_name}, skipping scrape save.")

            # Continue AI analysis logic (unchanged)
            competitor_data_for_ai = get_competitor_data(item_name, include_url=False)
            competitor_data_for_frontend = get_competitor_data(item_name, include_url=True)

            ai_response, reasoning, suggested_price = generate_price_analysis(
                item_name, description, competitor_data_for_ai
            )

            analysis_result = save_analysis_to_db(
                item_name, description, reasoning, suggested_price, competitor_data_for_frontend
            )

            results.append({
                "barcode": barcode,
                "success": True,
                "suggested_price": suggested_price,
                "reasoning": reasoning,
                "competitor_data": competitor_data_for_frontend,
                "competitor_count": analysis_result["competitor_count"],
                "analysis_id": analysis_result["analysis_id"]
            })

        return JsonResponse({"success": True, "results": results})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_GET
def price_analysis_detail(request, analysis_id):
    analysis = get_object_or_404(PriceAnalysis.objects.select_related("item"), pk=analysis_id)

    competitor_data = get_competitor_data(analysis.item.title, include_url=True)
    competitor_lines = competitor_data.split("\n") if competitor_data else []

    return JsonResponse({
        "success": True,
        "analysis_id": analysis.id,
        "item_title": analysis.item.title,
        "suggested_price": analysis.suggested_price,
        "reasoning": analysis.reasoning,
        "confidence": analysis.confidence,
        "created_at": analysis.created_at,
        "competitor_data": competitor_lines,
        "competitor_count": len(competitor_lines),
        "item_description": analysis.item.description,   # <-- add this
        "serial_number": analysis.item.serial_number,     # <-- add this
    })


# ----------------------- HOME PAGE VIEWS -------------------------------------
def individual_item_analysis_view(request):
    return render(request, "analysis/individual_item_analysis.html")


def home_view(request):
    return render(request, "home.html")


def individual_item_analyser_view(request):
    # Handle prefilled data from URL parameters
    prefilled_data = get_prefilled_data(request)
    
    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        return handle_item_analysis_request(request)
    
    # GET (render page)
    return render(request, "analysis/individual_item_analyser.html", {"prefilled_data": prefilled_data})

from .forms import CategoryForm, MarginRuleForm, GlobalMarginRuleForm


def item_buying_analyser_view(request):
    # Handle prefilled data from URL parameters
    prefilled_data = get_prefilled_data(request)

    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        return handle_item_analysis_request(request)

    # GET (render page)
    return render(request, "analysis/item_buying_analyser.html", {"prefilled_data": prefilled_data})


# Note: This is technically not in the home page right now
def inventory_free_stock_view(request):
    inventory_items = (
        InventoryItem.objects
        .filter(status="free_stock")
        .select_related("agreement", "market_item")
        .prefetch_related(
            Prefetch("market_item__listings")
        )
    )
    return render(request, "deprecated/inventory_free_stock.html", {"inventory_items": inventory_items})


# --------------------- END HOME PAGE VIEWS -------------------------------------

def category_list(request):
    categories = Category.objects.all()
    global_rules = GlobalMarginRule.objects.all()
    return render(request, "rules/categories.html", {
        "categories": categories,
        "global_rules": global_rules,
    })


def category_detail(request, pk):
    category = get_object_or_404(Category, pk=pk)
    rules = category.rules.all()  # MarginRules related to this category

    return render(request, "rules/category_detail.html", {
        "category": category,
        "rules": rules,
    })


def add_category(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("category_list")
    else:
        form = CategoryForm()
    return render(request, "rules/add_category.html", {"form": form})

def edit_category(request, pk):
    category = get_object_or_404(Category, pk=pk)

    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            return redirect("category_detail", pk=category.pk)
    else:
        form = CategoryForm(instance=category)

    return render(request, "rules/add_category.html", {
        "form": form,
        "category": category,
        "is_edit": True,  # optional flag for template
    })

def manage_category(request, pk):
    category = get_object_or_404(Category, pk=pk)
    # Here you could list/edit rules later
    return render(request, "rules/manage_category.html", {"category": category})


def delete_category(request, pk):
    category = get_object_or_404(Category, pk=pk)

    if request.method == "POST":
        category.delete()
        return redirect("category_list")  # Redirect to the category list page

    # Optional: show a confirmation page
    return render(request, "rules/delete_category_confirm.html", {"category": category})


def add_rule(request, category_pk):
    category = get_object_or_404(Category, pk=category_pk)

    if request.method == "POST":
        form = MarginRuleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.category = category  # link rule to this category
            rule.save()
            return redirect("category_detail", pk=category.pk)
    else:
        form = MarginRuleForm()

    return render(request, "rules/add_edit_rule.html", {
        "form": form,
        "category": category,
        "is_edit": False,
    })

def edit_rule(request, pk):
    rule = get_object_or_404(MarginRule, pk=pk)
    category = rule.category

    if request.method == "POST":
        form = MarginRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            return redirect("category_detail", pk=category.pk)
    else:
        form = MarginRuleForm(instance=rule)

    return render(request, "rules/add_edit_rule.html", {
        "form": form,
        "category": category,
        "is_edit": True,
    })


def delete_rule(request, pk):
    rule = get_object_or_404(MarginRule, pk=pk)
    category = rule.category

    if request.method == "POST":
        rule.delete()
        return redirect("category_detail", pk=category.pk)

    # Optional confirmation page
    return render(request, "rules/delete_rule_confirm.html", {"rule": rule, "category": category})


def add_global_rule(request):
    if request.method == "POST":
        form = GlobalMarginRuleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("category_list")
        else:
            print(form.errors)
    else:
        form = GlobalMarginRuleForm()

    return render(request, "rules/add_edit_global_rule.html", {
        "form": form,
        "is_edit": False,
    })


def edit_global_rule(request, pk):
    rule = get_object_or_404(GlobalMarginRule, pk=pk)

    if request.method == "POST":
        form = GlobalMarginRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            return redirect("category_list")
    else:
        form = GlobalMarginRuleForm(instance=rule)

    return render(request, "rules/add_edit_global_rule.html", {
        "form": form,
        "is_edit": True,
    })


def delete_global_rule(request, pk):
    rule = get_object_or_404(GlobalMarginRule, pk=pk)

    if request.method == "POST":
        rule.delete()
        return redirect("category_list")

    return render(request, "rules/delete_global_rule_confirm.html", {"rule": rule})


@csrf_exempt
@require_POST
def detect_irrelevant_competitors(request):
    """
    Accepts a search query and a list of competitor listings, 
    returns indices of irrelevant listings.
    """
    try:
        data = json.loads(request.body)
        search_query = (data.get("search_query") or "").strip()
        competitor_list = data.get("competitor_list") or []  # list of strings
        item_description = (data.get("item_description") or "").strip()

        if not search_query or not competitor_list:
            return JsonResponse({"success": False, "error": "Missing search_query or competitor_list"}, status=400)

        # Build prompt for Gemini
        prompt_lines = [
            "You are filtering competitor listings for relevance.",
            f"The user searched for: \"{search_query}\"",
        ]

        if item_description:
            prompt_lines.append(f"Item description: \"{item_description}\"")

        prompt_lines.append("Here is the list of competitor listings with indices:")
        for idx, title in enumerate(competitor_list):
            prompt_lines.append(f"{idx}: {title}")

        prompt_lines.append(
            "Task: Identify which indices are NOT relevant to the search query and description.\n"
            "- Relevant means: it is the same product of the product searched.\n"
            "- Irrelevant means: wrong model, accessories, games, unrelated items, a variation (such as a Pro vs a Pro Max), or a different product condition (brand new vs used for several years).\n"
            "- Do not include any reasoning, only the indices.\n"
            "- Be lenient, do NOT determine the relevant listings as irrelevant.\n"
            "- IMPORTANT: Ignore the description for judging relevance unless it contains clear model or variant information. Focus primarily on product title matching."
            "- Respond ONLY with an array of integers, e.g., [0, 2, 5].\n"
            "- DO NOT include any reasoning, text, or extra characters.\n"
            "- If all listings are relevant, respond with an empty array [].\n"
            "- STRICTLY FOLLOW ARRAY FORMAT, no trailing commas or extra spaces."
        )

        prompt = "\n".join(prompt_lines)

        # Call Gemini
        ai_response = call_gemini_sync(prompt)

        # Attempt to parse JSON array from AI response
        try:
            irrelevant_indices = json.loads(ai_response)
            if not isinstance(irrelevant_indices, list):
                irrelevant_indices = []
        except Exception:
            irrelevant_indices = []
            print("Failed to parse irrelevant indices!")

        return JsonResponse({
            "success": True,
            "irrelevant_indices": irrelevant_indices,
            "raw_ai_response": ai_response
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


CURRENT_GEN_MODELS = {
    "iPhone": "iPhone 17",
    "Samsung Galaxy": "Galaxy S25",
    "Google Pixel": "Pixel 9",
}


from ai_context import MARGINS
@csrf_exempt
@require_POST
def buying_range_analysis(request):
    """
    API endpoint to calculate buying range using Gemini
    """
    try:
        data = json.loads(request.body)
        item_name = (data.get("item_name") or "").strip()
        description = (data.get("description") or "").strip()
        suggested_price = (data.get("suggested_price") or "").strip()
        profit_margin = (data.get("margin") or "").strip()

        if not (item_name and description and suggested_price and profit_margin):
            return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

        # Format margins nicely for Gemini
        lines = []
        for category, subcat, min_offer, max_offer, notes in MARGINS:
            lines.append(f"- {category} → {subcat}: {min_offer}–{max_offer}% ({notes})")
        margins_context = "\n".join(lines)

        prompt = (
            f"Item: {item_name}\n"
            f"Description: {description}\n"
            f"Selling Price: {suggested_price}\n"
            "Company Buying Margin Rules (for context):\n"
            f"{margins_context}\n\n"
            "Task: Calculate an appropriate buying-in % of the selling price to offer the customer for this product, "
            "considering the item name, description, and the price we will sell it for.\n"
            "- We are a pawn shop in a similar mold to CashConverters and CashGenerators.\n"
            "- Factor in resale value & current market demand based on the suggested selling price, liquidity/turnover speed (how quickly we can realistically sell), authentication/theft risk, storage/display costs, current inventory levels, and any taxes/fees.\n"
            "- The buying price must allow achieving at least the given profit margin: {profit_margin} on the expected selling price. Use the formula: buying_price ≤ suggested_price × (1 - {profit_margin}/100). If {profit_margin} is not provided, assume 40%.\n"
            "- Suggest BOTH a MIN and MAX %: MIN = first % of selling price we will offer the customer; MAX = the maximum % of the selling price we will pay for this product.\n"
            f"NOTE: As of NOW, the current generation models are:\n"
            f"- iPhone: {CURRENT_GEN_MODELS['iPhone']}\n"
            f"- Samsung Galaxy: {CURRENT_GEN_MODELS['Samsung Galaxy']}\n"
            f"- Google Pixel: {CURRENT_GEN_MODELS['Google Pixel']}\n"
            "\nUse this when deciding whether a device is 'current gen', '1–2 years old', etc.\n\n"
            "You may deviate from the percentage provided depending on the item's desirability and sellability, but ONLY the higher end."
            "- OUTPUT FORMAT:"
            "your reasoning (within 100 words)"
            "FINAL:MIN%–MAX% (for example: FINAL:35%-45%).\n"
        )

        ai_response = call_gemini_sync(prompt)

        return JsonResponse({
            "success": True,
            "ai_response": ai_response,
            "prompt": prompt
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)



