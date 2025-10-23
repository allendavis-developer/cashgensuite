from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db import transaction
from django.db.models import Q, Prefetch
from django.utils import timezone

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from pricing.models import (
    ListingSnapshot, 
    InventoryItem, 
    MarketItem, 
    CompetitorListing, 
    CompetitorListingHistory, 
    PriceAnalysis, 
    Category, 
    MarginRule, 
    GlobalMarginRule,
    Manufacturer,
    ItemModel,
    CategoryAttribute
    )

import json, traceback, re
from decimal import Decimal, InvalidOperation

from pricing.utils.ai_utils import client
from pricing.utils.ai_utils import call_gemini_sync, generate_price_analysis, generate_bulk_price_analysis
from pricing.utils.competitor_utils import get_competitor_data
from pricing.utils.analysis_utils import process_item_analysis, save_analysis_to_db
from pricing.utils.search_term import build_search_term


def get_prefilled_data(request):
    return {
        "name": request.GET.get("name", ""),
        "description": request.GET.get("description", ""),
        "barserial": request.GET.get("barserial", ""),
        "cost_price": request.GET.get("cost_price", ""),
        "barcode": request.GET.get("barcode", ""),
        "branch": request.GET.get("branch", ""),  
    }


def handle_item_analysis_request(request):
    """Handle JSON POST request for item analysis"""
    try:
        data = json.loads(request.body)
        return process_item_analysis(data)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)



def bulk_analysis(request):
    return render(request, 'analysis/bulk_analysis.html')



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


@require_POST
def check_existing_items(request):
    try:
        data = json.loads(request.body)
        category = data.get("category")
        model = data.get("model")
        attributes = data.get("attributes", {})

        if not category or not model:
            return JsonResponse({"success": False, "error": "Category and model are required."})

        # Build search term
        search_term = build_search_term(model, category, attributes)


        # Get competitor data
        competitor_data = get_competitor_data(search_term, include_url=True)
        competitor_lines = competitor_data.split("\n") if competitor_data else []


        return JsonResponse({
            "success": True,
            "search_term": search_term,
            "competitor_data": competitor_lines,
            "competitor_count": len(competitor_lines)
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


# ----------------------- HOME PAGE VIEWS -------------------------------------
def home_view(request):
    return render(request, "home.html")


@csrf_exempt
def individual_item_analyser_view(request):
    # Handle prefilled data from URL parameters
    prefilled_data = get_prefilled_data(request)

    categories = Category.objects.all()

    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        return handle_item_analysis_request(request)
    
    # GET (render page)
    return render(request, "analysis/individual_item_analyser.html", {"prefilled_data": prefilled_data, "categories": categories})

from .forms import CategoryForm, MarginRuleForm, GlobalMarginRuleForm


def item_buying_analyser_view(request):
    # Handle prefilled data from URL parameters
    prefilled_data = get_prefilled_data(request)
    categories = Category.objects.all()

    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        return handle_item_analysis_request(request)

    # GET (render page)
    return render(request, "analysis/item_buying_analyser.html", {"prefilled_data": prefilled_data, "categories": categories})

def repricer_view(request):
    return render(request, "analysis/repricer.html")


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
    manufacturers = Manufacturer.objects.all().order_by("name")

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
        "manufacturers": manufacturers,  
    })

def edit_rule(request, pk):
    rule = get_object_or_404(MarginRule, pk=pk)
    category = rule.category
    manufacturers = Manufacturer.objects.all().order_by("name")

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
        "manufacturers": manufacturers,  
    })

def get_match_value_choices(request):
    rule_type = request.GET.get("rule_type")
    data = []

    if rule_type == "manufacturer":
        data = list(Manufacturer.objects.values_list("name", flat=True))
    elif rule_type == "model":
        data = list(ItemModel.objects.values_list("name", flat=True))

    return JsonResponse({"choices": data})


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
def buying_range_analysis(request):
    """
    API endpoint to calculate buying range using Gemini
    """
    try:
        data = json.loads(request.body)
        item_name = (data.get("item_name") or "").strip()
        attributes = data.get("attributes", {})
        category_id = data.get('category')
        manufacturer_id = data.get('manufacturer')

        if not (item_name and category_id):
            return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

        print("Received request with ", data)

        # Find Category and Manufacturer
        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return JsonResponse({"success": False, "error": "Invalid category"}, status=404)

        manufacturer = None
        if manufacturer_id:
            try:
                manufacturer = Manufacturer.objects.get(id=manufacturer_id)
            except Manufacturer.DoesNotExist:
                return JsonResponse({"success": False, "error": "Invalid manufacturer"}, status=404)

        # Find applicable MarginRule(s)
        rules = MarginRule.objects.filter(category=category, is_active=True)

        # Manufacturer-based rule
        manufacturer_rule = None
        if manufacturer:
            manufacturer_rule = rules.filter(rule_type='manufacturer', match_value__iexact=manufacturer.name).first()

        # Model-based rule (match item_name)
        model_rule = rules.filter(rule_type='model', match_value__iexact=item_name).first()

        # Calculate effective margin (category base + adjustments)
        effective_margin = category.base_margin
        rule_matches = []

        if manufacturer_rule:
            effective_margin += manufacturer_rule.adjustment
            rule_matches.append({
                "type": "manufacturer",
                "match": manufacturer_rule.match_value,
                "adjustment": manufacturer_rule.adjustment,
            })

        if model_rule:
            effective_margin += model_rule.adjustment
            rule_matches.append({
                "type": "model",
                "match": model_rule.match_value,
                "adjustment": model_rule.adjustment,
            })

        #  Return analysis summary
        return JsonResponse({
            "success": True,
            "category": category.name,
            "manufacturer": manufacturer.name if manufacturer else None,
            "base_margin": category.base_margin,
            "effective_margin": effective_margin,
            "rules_applied": rule_matches,
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@csrf_exempt
@require_POST
def save_scraped_data(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        item_name = data.get('item_name')
        results = data.get('results', [])
        category_id = data.get('category')  
        model_id = data.get('item_model')   
        attributes = data.get('attributes', {})  

        if not results:
            return JsonResponse({'success': False, 'error': 'No results to process'})

        now = timezone.now()
        market_item = MarketItem.objects.filter(title__iexact=item_name.strip()).first()
        if not market_item:
            market_item = MarketItem.objects.create(
                title=item_name.strip(),
                category_id=category_id,
                item_model_id=model_id
            )
        else:
            # Update category/model if provided
            if category_id:
                market_item.category_id = category_id
            if model_id:
                market_item.item_model_id = model_id
            market_item.save()


        # Load existing listings for this market item
        existing_listings = {
            (l.competitor, l.stable_id): l
            for l in CompetitorListing.objects.filter(market_item=market_item)
        }

        listings_to_create = []
        listings_to_update = []
        new_or_updated_listings = {}
        histories_to_create = []

        for item in results:
            competitor = item.get('competitor')
            stable_id = item.get('stable_id') or item.get('id') or item.get('url')
            if not competitor or not stable_id:
                continue

            key = (competitor, stable_id)
            price = float(item.get('price', 0))
            title = item.get('title', '')
            description = item.get('description', '')
            condition = item.get('condition', '')
            store = item.get('store', '')
            url = item.get('url', '')

            if key in existing_listings:
                listing = existing_listings[key]

                changed = (price != listing.price)

                # Update fields
                listing.price = price
                listing.title = title
                listing.description = description
                listing.condition = condition
                listing.store_name = store
                listing.url = url
                listing.is_active = True
                listing.last_seen = now

                listings_to_update.append(listing)
                new_or_updated_listings[key] = listing

                if changed:
                    histories_to_create.append(
                        CompetitorListingHistory(
                            listing=listing,
                            price=price,
                            title=title,
                            condition=condition,
                            timestamp=now,
                        )
                    )

                    print("HISTORY CHANGEDDDDDDD listing", listing.title, " with url:", listing.url)

            else:
                # ✅ New listing: always create history
                listing = CompetitorListing(
                    market_item=market_item,
                    competitor=competitor,
                    stable_id=stable_id,
                    price=price,
                    title=title,
                    description=description,
                    condition=condition,
                    store_name=store,
                    url=url,
                    is_active=True,
                    last_seen=now,
                )
                listings_to_create.append(listing)
                new_or_updated_listings[key] = listing

        # --- Write to DB ---
        with transaction.atomic():
            if listings_to_create:
                created = CompetitorListing.objects.bulk_create(listings_to_create)
                for l in created:
                    new_or_updated_listings[(l.competitor, l.stable_id)] = l
                    # ✅ Add history for newly created listings
                    histories_to_create.append(
                        CompetitorListingHistory(
                            listing=l,
                            price=l.price,
                            title=l.title,
                            condition=l.condition,
                            timestamp=now,
                        )
                    )

            if listings_to_update:
                CompetitorListing.objects.bulk_update(
                    listings_to_update,
                    [
                        'price', 'title', 'description', 'condition',
                        'store_name', 'url', 'is_active', 'last_seen'
                    ]
                )

        # --- Bulk insert histories (if any) ---
        if histories_to_create:
            CompetitorListingHistory.objects.bulk_create(histories_to_create)

        # --- Update MarketItem last_scraped ---
        market_item.last_scraped = now
        market_item.save()


        print(f"✅ Created {len(listings_to_create)} listings, updated {len(listings_to_update)}, "
              f"added {len(histories_to_create)} histories")

        return JsonResponse({
            'success': True,
            'created': len(listings_to_create),
            'updated': len(listings_to_update),
            'histories': len(histories_to_create),
        })

    except Exception as e:
        print("❌ Error saving scraped data:", e)
        return JsonResponse({'success': False, 'error': str(e)})

from django.contrib.admin.views.decorators import staff_member_required
from .models import ItemModel
@staff_member_required
def get_models(request):
    """AJAX endpoint to get models filtered by category and optionally manufacturer"""
    category_id = request.GET.get('category')
    manufacturer_id = request.GET.get('manufacturer')
    
    if not category_id:
        return JsonResponse({'models': []})
    
    models = ItemModel.objects.filter(category_id=category_id)
    
    if manufacturer_id:
        models = models.filter(manufacturer_id=manufacturer_id)
    
    models_data = [
        {
            'id': model.id,
            'name': str(model)  # This will show "Apple iPhone 15"
        }
        for model in models.order_by('manufacturer__name', 'name')
    ]
    
    return JsonResponse({'models': models_data})


# ----------------------------------------------------------------------------------------
# ENDPOINTS FOR DROPDOWN CATEGORY, MANUFACTURER, MODEL, ATTRIBUTE SEARCHING AND CREATION
# ----------------------------------------------------------------------------------------


def manufacturers(request):
    manufacturers = Manufacturer.objects.all().order_by('name')
    data = [{"id": m.id, "name": m.name} for m in manufacturers]
    return JsonResponse(data, safe=False)


def models(request):
    category_id = request.GET.get('category')
    manufacturer_id = request.GET.get('manufacturer')
    models = ItemModel.objects.filter(category_id=category_id, manufacturer_id=manufacturer_id)
    data = [{"id": m.id, "name": m.name} for m in models]
    return JsonResponse(data, safe=False)

def category_attributes(request):
    category_id = request.GET.get('category')
    attrs = CategoryAttribute.objects.filter(category_id=category_id).order_by('order')
    data = [
        {
            "id": a.id,
            "name": a.name,
            "label": a.label,
            "field_type": a.field_type,
            "required": a.required,
            "options": a.options or []
        } for a in attrs
    ]
    return JsonResponse(data, safe=False)


@csrf_exempt
def add_category(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        if not name:
            return JsonResponse({'error': 'Name required'}, status=400)
        cat, _ = Category.objects.get_or_create(name=name)
        return JsonResponse({'id': cat.id, 'name': cat.name})

@csrf_exempt
def add_manufacturer(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = (data.get('name') or '').strip()
        if not name:
            return JsonResponse({'error': 'Name required'}, status=400)
        manufacturer, _ = Manufacturer.objects.get_or_create(name=name)
        return JsonResponse({'id': manufacturer.id, 'name': manufacturer.name})

@csrf_exempt
def add_model(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        manufacturer_id = data.get('manufacturer')
        category_id = data.get('category')
        if not (name and manufacturer_id and category_id):
            return JsonResponse({'error': 'Missing fields'}, status=400)
        model, _ = ItemModel.objects.get_or_create(
            name=name, 
            manufacturer_id=manufacturer_id, 
            category_id=category_id
        )
        return JsonResponse({'id': model.id, 'name': model.name})

@csrf_exempt
def add_attribute_option(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
        attribute_id = data.get('attribute_id')
        new_option = (data.get('option') or '').strip()

        if not attribute_id or not new_option:
            return JsonResponse({'error': 'attribute_id and option required'}, status=400)

        attr = CategoryAttribute.objects.get(id=attribute_id)

        # Ensure field type supports options
        if attr.field_type != 'select':
            return JsonResponse({'error': 'This attribute does not support options'}, status=400)

        # Initialize options list if empty
        current_options = attr.options or []

        # Avoid duplicates (case-insensitive)
        if any(o.lower() == new_option.lower() for o in current_options):
            return JsonResponse({'message': 'Option already exists', 'options': current_options})

        # Add new option
        current_options.append(new_option)
        attr.options = current_options
        attr.save()

        return JsonResponse({'message': 'Option added', 'options': current_options})

    except CategoryAttribute.DoesNotExist:
        return JsonResponse({'error': 'Attribute not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def generate_search_term(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            category = data.get("category")
            model = data.get("model")
            attributes = data.get("attributes", {})

            if not category or not model:
                return JsonResponse({"success": False, "error": "Category and model are required."}, status=400)

            # Build the search term - FIXED: model is the item_name
            search_term = build_search_term(model, category, attributes)  # ← CHANGED ORDER
            
            print("Model (item_name):", model)
            print("Category:", category)
            print("Attributes:", attributes)
            print("Search term:", search_term)
            
            return JsonResponse({
                "success": True,
                "data": {
                    "category": category,
                    "model": model,
                    "attributes": attributes,
                    "generated_search_term": search_term
                }
            })

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

    return JsonResponse({"success": False, "error": "Invalid request method"}, status=405)


class NegotiationTemplates:
    """Strategic negotiation response templates"""
    
    @staticmethod
    def get_opening_response(item_name, next_offer, customer_price, competitors, selling_reasoning, buying_reasoning):
        """First offer in negotiation"""
        comp_reference = NegotiationTemplates._format_competitor_reference(competitors, limit=2)
        
        responses = [
            f"• Thanks for bringing in the {item_name}",
            comp_reference,
            f"• Based on current market conditions, I can offer **£{next_offer:.2f}**",
            f"• This accounts for reconditioning costs and {selling_reasoning.lower()}",
            "• Happy to discuss if you have questions about the valuation"
        ]
        
        return [r for r in responses if r]  # Filter empty strings
    
    @staticmethod
    def get_mid_negotiation_response(item_name, next_offer, last_offer, customer_price, competitors, buying_reasoning, progress):
        """Moving up from previous offer"""
        comp_reference = NegotiationTemplates._format_competitor_reference(competitors, limit=2)
        increase = next_offer - last_offer if last_offer else 0
        
        responses = [
            f"• I can see you're firm on the value of this {item_name}",
            comp_reference,
            f"• I can move to **£{next_offer:.2f}** (up £{increase:.2f} from my previous offer)",
            "• This is a competitive offer given our overhead and resale timeline",
            "• Let me know if this works for you"
        ]
        
        return [r for r in responses if r]
    
    @staticmethod
    def get_maximum_response(item_name, next_offer, customer_price, competitors, buying_reasoning):
        """Final offer - at budget maximum"""
        comp_reference = NegotiationTemplates._format_competitor_reference(competitors, limit=3)
        
        responses = [
            f"• I appreciate you working with me on the {item_name}",
            comp_reference,
            f"• My absolute maximum is **£{next_offer:.2f}** - I can't go higher than this",
            "• At this price point, my margin is already very thin",
            "• If this works, I can complete the transaction immediately. If not, I understand"
        ]
        
        return [r for r in responses if r]
    
    @staticmethod
    def _format_competitor_reference(competitors, limit=2):
        """Format competitor data into natural references"""
        if not competitors:
            return "• Looking at similar items on the market, pricing is quite varied"
        
        # Take top N competitors by price (lowest first for buying justification)
        sorted_comps = sorted(competitors, key=lambda x: x.get('price', 999999))[:limit]
        
        if len(sorted_comps) == 1:
            c = sorted_comps[0]
            return f"• {c['competitor']} lists similar items at £{c['price']:.2f} ({c['condition']})"
        
        references = []
        for c in sorted_comps:
            references.append(f"{c['competitor']} at £{c['price']:.2f} ({c['condition']})")
        
        return f"• Current market: {', '.join(references)}"
    
    @staticmethod
    def get_customer_reply_options(at_maximum, next_offer, customer_price):
        """Generate realistic customer response options"""
        if at_maximum:
            return [
                f"• That's still below what I was hoping for, but I'll accept £{next_offer:.2f}",
                f"• Can you do £{customer_price:.2f}? That's my bottom line",
                "• I think I'll hold onto it for now and try elsewhere"
            ]
        
        # Mid-negotiation
        midpoint = (next_offer + customer_price) / 2
        return [
            f"• £{next_offer:.2f} is closer - let's do it",
            f"• I was hoping for at least £{midpoint:.2f} - can you meet me there?",
            "• Why is your offer lower than what I'm seeing online?"
        ]


@csrf_exempt
@require_POST
def negotiation_step(request):
    """
    Template-based negotiation - fast, predictable, no AI costs
    """
    try:
        data = json.loads(request.body)

        item_name = (data.get("item_name") or "").strip()
        description = (data.get("description") or "").strip()
        suggested_price = (data.get("suggested_price") or "").strip()
        buying_range = data.get("buying_range") or {}
        selling_reasoning = (data.get("selling_reasoning") or "").strip()
        buying_reasoning = (data.get("buying_reasoning") or "").strip()
        customer_input = (data.get("customer_input") or "").strip()
        conversation_history = data.get("conversation_history") or []
        selected_competitor_rows = data.get("selected_competitor_rows") or []

        if not item_name or not suggested_price or not buying_range:
            return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

        min_price = float(buying_range.get("min", 0))
        max_price = float(buying_range.get("max", 0))
        customer_price = float(customer_input) if customer_input else max_price

        # Determine last offer
        last_offer = None
        if conversation_history:
            last_offer = conversation_history[-1].get("assistant_offer")
            last_offer = float(last_offer) if last_offer else None

        # Calculate next offer (same logic as before)
        at_maximum = False
        if not conversation_history:
            next_offer = min(min_price + (max_price - min_price) * 0.1, customer_price)
        elif last_offer and last_offer >= max_price:
            next_offer = max_price
            at_maximum = True
        else:
            last_offer = last_offer if last_offer else min_price
            distance_to_target = min(customer_price, max_price) - last_offer

            if distance_to_target <= 0:
                next_offer = max_price
                at_maximum = True
            else:
                increment = max(distance_to_target * 0.4, 2)
                max_step = (max_price - min_price) * 0.3
                increment = min(increment, max_step)
                next_offer = min(last_offer + increment, max_price, customer_price)

                if next_offer >= max_price:
                    next_offer = max_price
                    at_maximum = True

        # Calculate progress
        progress = (
            round((next_offer - min_price) / (max_price - min_price) * 100, 1)
            if max_price > min_price else 100
        )

        # Generate response using templates
        if not conversation_history:
            your_response = NegotiationTemplates.get_opening_response(
                item_name, next_offer, customer_price, 
                selected_competitor_rows, selling_reasoning, buying_reasoning
            )
        elif at_maximum:
            your_response = NegotiationTemplates.get_maximum_response(
                item_name, next_offer, customer_price,
                selected_competitor_rows, buying_reasoning
            )
        else:
            your_response = NegotiationTemplates.get_mid_negotiation_response(
                item_name, next_offer, last_offer, customer_price,
                selected_competitor_rows, buying_reasoning, progress
            )

        customer_reply_options = NegotiationTemplates.get_customer_reply_options(
            at_maximum, next_offer, customer_price
        )

        # Build response - convert list to HTML for better formatting
        formatted_response = "<br>".join(your_response)
        
        response_data = {
            "your_response": formatted_response,  # HTML formatted
            "your_response_bullets": your_response,  # Original list
            "customer_reply_options": customer_reply_options,
            "suggested_offer": f"£{next_offer:.2f}",
            "at_maximum": at_maximum,
            "negotiation_progress": progress
        }

        return JsonResponse({
            "success": True,
            "ai_response": response_data,  # Keep same key for frontend compatibility
            "at_maximum": at_maximum,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@csrf_exempt
def save_listing(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid method"}, status=405)

    try:
        data = json.loads(request.body)

        def to_decimal(value):
            if value in [None, "", "null", "-"]:
                return None
            try:
                # Clean the value (remove £, commas, etc.)
                cleaned = str(value).replace('£', '').replace(',', '').strip()
                return Decimal(cleaned)
            except (InvalidOperation, ValueError):
                return None

        title = data.get("item_name")
        branch = data.get("branch", "")
        serial = data.get("serial_number") or None

        # 1️⃣ Find or create InventoryItem
        item, created_item = InventoryItem.objects.get_or_create(
            title=title,
            defaults={
                "status": "free_stock",
                "description": data.get("description", ""),
                "serial_number": serial,
            }
        )

        # 2️⃣ Determine the listing price
        listing_price = (
            to_decimal(data.get("listing_price")) or  # From modal if available
            to_decimal(data.get("cc_recommended_price")) or 
            to_decimal(data.get("cg_recommended_price")) or 
            to_decimal(data.get("rrp_with_margin")) or
            to_decimal(data.get("market_average"))
        )

        if not listing_price:
            return JsonResponse({
                "success": False, 
                "error": "No valid price found. Please analyze prices first."
            }, status=400)

        # 3️⃣ Find or create Listing WITH PRICE
        listing, created_listing = Listing.objects.get_or_create(
            item=item,
            branch=branch,
            defaults={
                "price": listing_price,
                "title": title,
                "description": data.get("description", ""),
                "platform": "WebEpos",  # or whatever platform you're using
            }
        )

        # If listing already exists, update its price
        if not created_listing:
            listing.price = listing_price
            listing.title = title
            listing.description = data.get("description", "")
            listing.save()

        # 4️⃣ Create new Snapshot linked to this listing
        snapshot = ListingSnapshot.objects.create(
            listing=listing,
            item_name=title,
            description=data.get("description"),
            cost_price=to_decimal(data.get("cost_price")),
            user_margin=to_decimal(data.get("user_margin")),
            market_range=data.get("market_range"),
            market_average=to_decimal(data.get("market_average")),
            cex_avg=to_decimal(data.get("cex_avg")),
            cex_discounted=to_decimal(data.get("cex_discounted")),
            rrp_with_margin=to_decimal(data.get("rrp_with_margin")),
            cc_lowest=to_decimal(data.get("cc_lowest")),
            cc_avg=to_decimal(data.get("cc_avg")),
            cg_lowest=to_decimal(data.get("cg_lowest")),
            cg_avg=to_decimal(data.get("cg_avg")),
            cc_recommended_price=to_decimal(data.get("cc_recommended_price")),
            cg_recommended_price=to_decimal(data.get("cg_recommended_price")),
            reasoning=data.get("reasoning", ""),
            competitors=data.get("competitors", []),
        )

        return JsonResponse({
            "success": True,
            "inventory_item_id": item.id,
            "listing_id": listing.id,
            "snapshot_id": snapshot.id,
            "listing_price": str(listing_price),
            "created_item": created_item,
            "created_listing": created_listing,
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())  # For debugging
        return JsonResponse({"success": False, "error": str(e)}, status=400)