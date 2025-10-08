from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Q, Prefetch

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from pricing.models import InventoryItem, MarketItem, CompetitorListing, PriceAnalysis, Category, MarginRule, GlobalMarginRule

import json, traceback, re

from pricing.utils.ai_utils import call_gemini_sync, generate_price_analysis, generate_bulk_price_analysis
from pricing.utils.competitor_utils import get_competitor_data
from pricing.utils.analysis_utils import process_item_analysis, save_analysis_to_db

@csrf_exempt
def generate_search_term(request):
    """
    Generate a concise, high-performing search term for an item.
    """
    try:
        data = json.loads(request.body)
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        specifications = data.get("specifications") or {}  # <-- new


        if not name:
            return JsonResponse({"success": False, "error": "Missing item name."})

        print("Received specifications:", specifications)

        # ✨ Build the Gemini prompt
        prompt = f"""
        You are a retail data intelligence assistant.

        Based on the following product details, generate a concise, optimized
        search query that would return the most relevant marketplace listings
        for price comparison and analysis.

        - Product Name: {name}
        - Description: {description}
        - Specifications: {json.dumps(specifications)}

        Output only the ideal search term (2–8 words). 
        For Phones: MODEL NAME STORAGE_CAPACITY is the output format. 
        Do not be specific, be general. Don't include details that filter our searches too much. DO NOT INCLUDE COLOUR INFORMATION. 
        Do not include commentary or punctuation.
        """

        # 🔮 Call Gemini synchronously
        search_term = call_gemini_sync(prompt)
        return JsonResponse({
            "success": True,
            "search_term": search_term,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


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
            urgency = int(item_data.get("urgency", 3))  # per item

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

            ai_response, reasoning, suggested_price = generate_bulk_price_analysis(
                item_name, description, competitor_data_for_ai, cost_price, urgency
            )

            analysis_result = save_analysis_to_db(
                item_name, description, reasoning, suggested_price, competitor_data_for_frontend, cost_price
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
        "cost_price": analysis.cost_price,
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


# -------------------  RULES PAGE VIEWS ---------------------------------------
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
    Accepts a search query, description, and structured list of competitor listings.
    Returns indices of irrelevant listings.
    """
    try:
        data = json.loads(request.body)
        search_query = (data.get("search_query") or "").strip()
        item_description = (data.get("item_description") or "").strip()
        competitor_list = data.get("competitor_list") or []  # list of dicts: [{title, store, price}]

        if not search_query or not competitor_list:
            return JsonResponse(
                {"success": False, "error": "Missing search_query or competitor_list"},
                status=400,
            )

        # 🟠 Auto-mark any competitors with missing/null price as irrelevant
        irrelevant_indices = [
            i for i, comp in enumerate(competitor_list)
            if comp.get("price") in [None, "", "null"]
        ]

        # Build readable version for AI (only those with valid prices)
        filtered_competitors = [
            (i, comp)
            for i, comp in enumerate(competitor_list)
            if i not in irrelevant_indices
        ]

        prompt_lines = [
            "You are filtering competitor listings for relevance.",
            f"The user searched for: \"{search_query}\"",
        ]

        if item_description:
            prompt_lines.append(f"Item description: \"{item_description}\"")

        prompt_lines.append("Here is the list of competitor listings with indices:")
        for idx, comp in filtered_competitors:
            title = comp.get("title", "Unknown Title")
            store = comp.get("store", "Unknown Store")
            price = comp.get("price", "N/A")
            prompt_lines.append(f"{idx}: {title} (Store: {store}, Price: £{price})")
        
        prompt_lines.append(
            "Task: Identify which indices are NOT relevant to the search query and description.\n"
            "- Relevant means: it is the same product of the product searched.\n"
            "- Irrelevant means: wrong model, accessories, games, unrelated items, a variation (such as a Pro vs a Pro Max).\n"
            "- Do not include any reasoning, only the indices.\n"
            "- Be AS LENIENT as possible, do NOT determine the relevant listings as irrelevant.\n"
            "- **IMPORTANT:** ALWAYS mark listings from the following stores as irrelevant, even if they appear fine: Cash Generator Warrington, Cash Generator Netherton, Cash Generator Wythenshawe.\n"
            "- IMPORTANT: Ignore the description for judging relevance unless it contains clear model or variant information. Focus primarily on product title matching."
            "- Respond ONLY with an array of integers, e.g., [0, 2, 5].\n"
            "- If all listings are relevant, respond with an empty array [].\n"
            "- STRICTLY FOLLOW ARRAY FORMAT, no trailing commas or extra spaces."
        )

        prompt = "\n".join(prompt_lines)
        # 🧠 Call Gemini model
        ai_response = call_gemini_sync(prompt)


        # Attempt to parse JSON array from AI response
        try:
            ai_irrelevant_indices = json.loads(ai_response)
            if not isinstance(ai_irrelevant_indices, list):
                ai_irrelevant_indices = []
        except Exception:
            ai_irrelevant_indices = []
            print("⚠ Failed to parse irrelevant indices from AI response!")

        # Combine AI-excluded + null-price indices (deduplicated + sorted)
        final_irrelevant = sorted(set(irrelevant_indices + ai_irrelevant_indices))

        return JsonResponse({
            "success": True,
            "irrelevant_indices": final_irrelevant,
            "auto_flagged_null_prices": irrelevant_indices,
            "raw_ai_response": ai_response,
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


@csrf_exempt
@require_POST
def negotiation_step(request):
    """
    Professional AI-assisted negotiation step.
    Starts near MIN buying price, increments dynamically toward MAX,
    continues assisting even after reaching max. AI generates context-aware persuasive text.
    """
    try:
        data = json.loads(request.body)

        item_name = (data.get("item_name") or "").strip()
        description = (data.get("description") or "").strip()
        suggested_price = (data.get("suggested_price") or "").strip()
        buying_range = data.get("buying_range") or {}  # {"min": 30, "max": 40}
        selling_reasoning = (data.get("selling_reasoning") or "").strip()
        buying_reasoning = (data.get("buying_reasoning") or "").strip()
        customer_input = (data.get("customer_input") or "").strip()
        conversation_history = data.get("conversation_history") or []

        if not item_name or not suggested_price or not buying_range:
            return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

        min_price = float(buying_range.get("min", 0))
        max_price = float(buying_range.get("max", 0))
        customer_price = float(customer_input) if customer_input else max_price

        # Determine last offer from conversation history
        last_offer = None
        if conversation_history:
            last_offer = conversation_history[-1].get("assistant_offer")
            last_offer = float(last_offer) if last_offer else None

        # Determine next numeric offer
        at_maximum = False
        if not conversation_history:
            # First offer → slightly above MIN for a professional feel
            next_offer = min(min_price + (max_price - min_price) * 0.1, customer_price)
        elif last_offer and last_offer >= max_price:
            # Already at max - hold the line but continue assisting
            next_offer = max_price
            at_maximum = True
        else:
            # Dynamic increment toward customer target
            last_offer = last_offer if last_offer else min_price
            distance_to_target = min(customer_price, max_price) - last_offer
            
            if distance_to_target <= 0:
                next_offer = max_price
                at_maximum = True
            else:
                increment = max(distance_to_target * 0.4, 2)  # move 40% of remaining distance, at least £2
                max_step = (max_price - min_price) * 0.3       # cap at 30% of full range
                increment = min(increment, max_step)
                next_offer = min(last_offer + increment, max_price, customer_price)
                
                # Check if we've reached maximum
                if next_offer >= max_price:
                    next_offer = max_price
                    at_maximum = True

        # Flatten conversation context for AI prompt
        dialogue_context = "\n".join([
            f"Customer: {turn.get('customer','')}\nYou: {turn.get('assistant','')} (offered: {turn.get('assistant_offer','')})"
            for turn in conversation_history
        ]) if conversation_history else "This is the opening of the negotiation."

        # Build context-aware prompt
        negotiation_stage = ""
        if not conversation_history:
            negotiation_stage = "This is your OPENING offer. Be friendly, acknowledge the item, and make a reasonable starting offer."
        elif at_maximum:
            negotiation_stage = f"You are at your MAXIMUM offer of £{max_price}. You CANNOT go higher. Be firm but empathetic. Explain why this is your best offer using the buying reasoning. Consider offering to finalize the deal or politely declining if the customer won't accept."
        else:
            negotiation_stage = f"You are moving from £{last_offer} to £{next_offer}. This is a {((next_offer - last_offer) / (max_price - min_price) * 100):.0f}% move within your range. Show you're negotiating in good faith."

        prompt = f"""
You are a professional pawn shop buyer negotiating to buy a used item. Instead of writing full paragraphs, generate **clear, concise bullet-pointed talking points** for your next response.

ITEM DETAILS:
- Item: {item_name}
- Description: {description}
- Intended resale price: £{suggested_price}
- Buying range: £{min_price} - £{max_price}
- Customer requested price: £{customer_price}

CONTEXT:
- Selling reasoning: {selling_reasoning}
- Buying reasoning: {buying_reasoning}
- Conversation history:
{dialogue_context}

NEGOTIATION STAGE:
{negotiation_stage}
- Last assistant offer: £{last_offer if last_offer else 'N/A'}
- Next offer: £{next_offer}
- At maximum offer? {at_maximum}

INSTRUCTIONS:
1. Write your response as **bullet points**, covering:
   - Acknowledging the customer and their offer
   - Your numeric offer (next_offer)
   - Specific reasoning from selling/buying context
   - Progress toward final agreement
2. Suggest 3 realistic **customer reply options**, also in bullet points.
3. Avoid paragraphs, generic phrases, or vague reasoning. Be precise, professional, and persuasive.
4. Include your numeric offer clearly as a bullet point.

OUTPUT FORMAT (JSON only):
{{
  "your_response": [
      "Bullet point 1",
      "Bullet point 2",
      "Bullet point 3"
  ],
  "customer_reply_options": [
      "Option 1",
      "Option 2",
      "Option 3"
  ]
}}
"""

        try:
            ai_response = call_gemini_sync(prompt)
        except Exception as e:
            traceback.print_exc()
            return JsonResponse({"success": False, "error": f"AI call failed: {str(e)}"}, status=500)

        # Safely parse AI JSON
        parsed = None
        try:
            parsed = json.loads(ai_response)
        except Exception:
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                except Exception:
                    parsed = None

        if not parsed:
            parsed = {
                "your_response": ai_response.strip(),
                "customer_reply_options": []
            }

        # Attach numeric offer and status for frontend
        parsed["suggested_offer"] = f"£{next_offer:.2f}"
        parsed["at_maximum"] = at_maximum
        parsed["negotiation_progress"] = round((next_offer - min_price) / (max_price - min_price) * 100, 1) if max_price > min_price else 100

        return JsonResponse({
            "success": True,
            "ai_response": parsed,
            "raw_ai_response": ai_response,
            "prompt": prompt,
            "at_maximum": at_maximum
        })

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)
