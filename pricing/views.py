from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db import transaction
from django.db.models import Q, Prefetch, Count
from django.utils import timezone
from django.db import connection, reset_queries


from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from pricing.models import (
    ListingSnapshot, 
    InventoryItem, 
    MarketItem, 
    CompetitorListing, 
    CompetitorListingHistory, 
    Category, 
    MarginRule, 
    GlobalMarginRule,
    Subcategory,
    ItemModel,
    CategoryAttribute,
    CEXPricingRule
    )

import json, traceback, re
from decimal import Decimal, InvalidOperation

from pricing.utils.ai_utils import call_gemini_sync, generate_price_analysis, generate_bulk_price_analysis
from pricing.utils.competitor_utils import get_competitor_data
from pricing.utils.analysis_utils import process_item_analysis, save_analysis_to_db
from pricing.utils.search_term import build_search_term, get_model_variants
from pricing.utils.pricing import get_effective_margin


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


@require_POST
def check_existing_items(request):
    try:
        data = json.loads(request.body)
        category = data.get("category")
        subcategory = data.get("subcategory")
        model = data.get("model")
        attributes = data.get("attributes", {})

        if not category or not model:
            return JsonResponse({"success": False, "error": "Category and model are required."})

        # Build search term
        search_term = build_search_term(model, category, subcategory, attributes)

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


def get_market_item(search_term):
    """Retrieve a market item by exact title match."""
    return MarketItem.objects.filter(title__iexact=search_term).first()

from collections import Counter


def get_competitor_price_stats(market_item):
    """Determine competitor price statistics including frequency, mode, and range."""

    def get_stats(listings):
        """Return mode, frequency, low, high, total for a list of listings."""
        if not listings:
            return None, 0, None, None, 0
        
        prices = [l.price for l in listings]
        price_counts = Counter(prices)
        mode_price = price_counts.most_common(1)[0][0]  # Most frequent price
        mode_count = price_counts[mode_price]           # how many listings share that mode price
        low = min(prices)
        high = max(prices)
        total = len(listings)
        return mode_price, mode_count, low, high, total

    # Fetch active listings for each competitor
    cc_listings = list(
        CompetitorListing.objects.filter(
            market_item=market_item, competitor="CashConverters", is_active=True
        ).order_by("price")
    )
    cg_listings = list(
        CompetitorListing.objects.filter(
            market_item=market_item, competitor="CashGenerator", is_active=True
        ).order_by("price")
    )

    # Compute stats for each
    cc_mode, cc_mode_count, cc_low, cc_high, cc_total = get_stats(cc_listings)
    cg_mode, cg_mode_count, cg_low, cg_high, cg_total = get_stats(cg_listings)

    return {
        "CashConverters": {
            "mode": cc_mode,
            "frequency": cc_mode_count,     # number of listings at the modal price
            "low": cc_low,
            "high": cc_high,
            "total_listings": cc_total,     # total active listings
        },
        "CashGenerator": {
            "mode": cg_mode,
            "frequency": cg_mode_count,
            "low": cg_low,
            "high": cg_high,
            "total_listings": cg_total,
        },
    }


def round_down_to_even(value):
    """Round down to the nearest even integer."""
    return (int(value) // 2) * 2


def compute_prices_from_cex_rule(market_item, cex_rule=None):
    """
    Fetch latest CEX prices for a given MarketItem and compute selling and buying prices.
    
    Updates market_item.cex_sale_price, market_item.cex_cash_trade_price, and market_item.cex_url.
    
    Selling price:
        - If cex_rule provided: cex_sale_price * cex_rule.cex_pct
        - Otherwise: cex_sale_price * 0.8 (default 20% discount)
    
    Buying price range:
        - start = 50% of selling price
        - end = CeX cash price if available, else 50% of selling price
        - Ensure start <= end
    """

    # --- Fetch first active CEX listing for this item ---
    cex_listing = CompetitorListing.objects.filter(
        competitor="CEX",
        market_item=market_item,
        is_active=True
    ).order_by("id").first()

    # --- Compute selling price ---
    sale_price = cex_listing.price or 0
    if cex_rule:
        selling_price = round(sale_price * cex_rule.cex_pct)
    else:
        selling_price = round(sale_price * 0.8)

    # --- Compute buying range ---
    buying_start_price = round(selling_price / 2)
    buying_end_price = cex_listing.trade_cash_price or round(selling_price / 2)

    if buying_start_price > buying_end_price:
        buying_start_price = round(buying_end_price * 0.8)

    return selling_price, buying_start_price, buying_end_price, cex_listing.trade_cash_price, cex_listing.price, cex_listing.url





def get_most_specific_cex_rule(category, subcategory=None, item_model=None):
    """
    Returns the most specific active CEX pricing rule for the given parameters.
    Priority:
    1. item_model + subcategory + category
    2. subcategory + category
    3. category only
    """
    rules = CEXPricingRule.objects.filter(category=category, is_active=True)
    
    # Filter by item_model if provided
    if item_model:
        rule = rules.filter(item_model=item_model, subcategory=subcategory).first()
        if rule:
            return rule

    # Filter by subcategory if provided
    if subcategory:
        rule = rules.filter(subcategory=subcategory, item_model__isnull=True).first()
        if rule:
            return rule

    # Fallback to category only
    rule = rules.filter(subcategory__isnull=True, item_model__isnull=True).first()
    return rule



@require_POST
def get_selling_and_buying_price(request):
    try:
        data = json.loads(request.body)
        category_id = data.get("categoryId")
        subcategory_id = data.get("subcategoryId")
        model_id = data.get("modelId")
        model = data.get("model")
        category = data.get("category")
        subcategory = data.get("subcategory")
        attributes = data.get("attributes", {})

        if not category or not model:
            return JsonResponse({"success": False, "error": "Category and model are required."})

        # Build search term and get market item
        search_term = build_search_term(model, category, subcategory, attributes)
        market_item = get_market_item(search_term)
        print("Searching for:", search_term, "Found:", market_item)

        if not market_item:
            return JsonResponse({"success": False, "error": "No matching market item found."})

        # Get competitor price stats
        competitor_stats = get_competitor_price_stats(market_item)

        # Get most specific CeX pricing rule
        cex_rule = get_most_specific_cex_rule(category_id, subcategory_id, model_id)

        # Compute final prices
        selling_price, buying_start, buying_end, cex_buying_price, cex_selling_price, cex_url = compute_prices_from_cex_rule(
            market_item, cex_rule
        )

        # Return response including competitor stats
        return JsonResponse({
            "success": True,
            "search_term": search_term,
            "selling_price": selling_price,
            "buying_start_price": buying_start,
            "buying_end_price": buying_end,
            "cex_buying_price": cex_buying_price,
            "cex_selling_price": cex_selling_price,
            "cex_url": cex_url,
            "competitor_stats": competitor_stats  # <-- added
        })

    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)





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


def item_buying_analyser_view(request):
    # Handle prefilled data from URL parameters
    prefilled_data = get_prefilled_data(request)
    categories = Category.objects.all()

    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        return handle_item_analysis_request(request)

    # GET (render page)
    return render(request, "analysis/item_buying_analyser.html", {"prefilled_data": prefilled_data, "categories": categories})


@csrf_exempt
@require_POST
def buying_range_analysis(request):
    try:
        data = json.loads(request.body)
        item_name = (data.get("item_name") or "").strip()
        attributes = data.get("attributes", {})
        category_id = data.get('category')
        subcategory_id = data.get('subcategory')

        if not (item_name and category_id):
            return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

        effective_margin, category, subcategory, rule_matches = get_effective_margin(
            category_id=category_id,
            subcategory_id=subcategory_id,
            model_name=item_name
        )

        return JsonResponse({
            "success": True,
            "category": category.name,
            "subcategory": subcategory.name if subcategory else None,
            "base_margin": category.base_margin,
            "effective_margin": effective_margin,
            "rules_applied": rule_matches,
        })

    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def get_scrape_sources_for_category(request):
    category_name = request.GET.get('category_name')  # get from query params
    if not category_name:
        return JsonResponse({"error": "category_name parameter is required"}, status=400)

    try:
        category = Category.objects.get(name__iexact=category_name)
        # Ensure scrape_sources is a list
        sources = category.scrape_sources if category.scrape_sources else []
        return JsonResponse(sources, safe=False)
    except Category.DoesNotExist:
        return JsonResponse({"error": "Category not found"}, status=404)


@csrf_exempt
@require_POST
def save_scraped_data(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        print("Received data:", data, flush=True)

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


        print(f"Created {len(listings_to_create)} listings, updated {len(listings_to_update)}, "
              f"added {len(histories_to_create)} histories")

        # # --- Fetch CeX cash price for the first active CEX listing ---
        # cex_listing = CompetitorListing.objects.filter(
        #     competitor="CEX",
        #     market_item=market_item,
        #     is_active=True
        # ).order_by("id").first()

        # if cex_listing:
        #     # Save the sale price from the first CEX listing
        #     market_item.cex_sale_price = cex_listing.price
        #     market_item.cex_url = f"https://uk.webuy.com/product-detail?id={cex_listing.stable_id}"
        #     if cex_listing.stable_id:
        #         cex_cash_trade_price = fetch_cex_cash_price(cex_listing.stable_id)
        #         if cex_cash_trade_price is not None:
        #             market_item.cex_cash_trade_price = cex_cash_trade_price
        #             print(f"Updated market_item.cex_cash_trade_price to {cex_cash_trade_price}")

        #     market_item.save()
        #     print(f"Updated market_item.cex_sale_price to {cex_listing.price}")


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
    """AJAX endpoint to get models filtered by category and optionally subcategory"""
    category_id = request.GET.get('category')
    subcategory_id = request.GET.get('subcategory')
    
    if not category_id:
        return JsonResponse({'models': []})
    
    models = ItemModel.objects.filter(category_id=category_id)
    
    if subcategory_id:
        models = models.filter(subcategory_id=subcategory_id)
    
    models_data = [
        {
            'id': model.id,
            'name': str(model)  # This will show "Apple iPhone 15"
        }
        for model in models.order_by('subcategory__name', 'name')
    ]
    
    return JsonResponse({'models': models_data})


# ----------------------------------------------------------------------------------------
# ENDPOINTS FOR DROPDOWN CATEGORY, SUBCATEGORY, MODEL, ATTRIBUTE SEARCHING AND CREATION
# ----------------------------------------------------------------------------------------


def categories(request):
    categories = list(Category.objects.values('id', 'name'))
    return JsonResponse({'categories': categories})


def subcategorys(request):
    # Get category id from GET parameters (e.g., ?category=1)
    category_id = request.GET.get('category')

    if category_id:
        subcategories = Subcategory.objects.filter(category_id=category_id).order_by('name')
        print("Got category id!")
    else:
        subcategories = Subcategory.objects.all().order_by('name')

    data = [{"id": s.id, "name": s.name} for s in subcategories]
    return JsonResponse(data, safe=False)


def models(request):
    category_id = request.GET.get('category')
    subcategory_id = request.GET.get('subcategory')
    models = ItemModel.objects.filter(
        subcategory__category_id=category_id,  # <-- traverse via subcategory
        subcategory_id=subcategory_id
    )
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
def add_subcategory(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = (data.get('name') or '').strip()
        category_id = data.get('category_id')  # <-- get the category ID from the request

        if not name:
            return JsonResponse({'error': 'Name required'}, status=400)
        if not category_id:
            return JsonResponse({'error': 'Category is required'}, status=400)

        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return JsonResponse({'error': 'Category does not exist'}, status=404)

        # Use 'defaults' to pass required foreign keys when creating
        subcategory, created = Subcategory.objects.get_or_create(
            name=name,
            defaults={'category': category}
        )

        return JsonResponse({'id': subcategory.id, 'name': subcategory.name})

@csrf_exempt
def add_model(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        subcategory_id = data.get('subcategory')
        category_id = data.get('category')
        if not (name and subcategory_id and category_id):
            return JsonResponse({'error': 'Missing fields'}, status=400)
        model, _ = ItemModel.objects.get_or_create(
            name=name, 
            subcategory_id=subcategory_id, 
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
            subcategory = data.get("subcategory") 
            model = data.get("model")
            attributes = data.get("attributes", {})

            print(data)

            if not category or not model:
                return JsonResponse({"success": False, "error": "Category and model are required."}, status=400)

            # Build the search term - FIXED: model is the item_name
            search_term = build_search_term(model, category, subcategory, attributes)  # ← CHANGED ORDER
            
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

@csrf_exempt
def save_input(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    data = json.loads(request.body)
    field = data.get('field')
    value = data.get('value')
    print(f"Received update: {field} = {value}")

    response_data = {'status': 'ok'}

    # -------------------------------------------------------
    # When the user selects a model, find variants dynamically
    # -------------------------------------------------------
    if field == 'model':
        try:
            model_id = int(value)
            item_model = ItemModel.objects.get(pk=model_id)
        except (ValueError, ItemModel.DoesNotExist):
            print(f"⚠️ Invalid model id: {value}")
            return JsonResponse(response_data)

        market_items = (
            MarketItem.objects
            .filter(item_model=item_model)
            .select_related('category', 'item_model')
        )

        print(f"📦 Found {market_items.count()} MarketItems for {item_model}:")
        for mi in market_items:
            print(f"   - {mi.id}: {mi.title} [{mi.category.name if mi.category else 'No category'}]")

        # Attributes defined for this ItemModel
        attrs = {
            av.attribute.name: av.get_display_value()
            for av in item_model.attribute_values.select_related('attribute')
        }
        print(f"Attributes for {item_model.name}: {attrs}")

        # -------------------------------------------------------
        # 🧩 Build and return variant options for this model
        # -------------------------------------------------------
        variants = get_model_variants(item_model)
        print(f"🧩 Variants for {item_model.name}: {variants}")

        # Send them back to the frontend so it can filter dropdowns
        response_data["variants"] = variants["variants"]

    return JsonResponse(response_data)

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


def ensure_hierarchy(category_name, subcategory_name, results):
    """
    Optimized hierarchy setup — prefetch + bulk create missing Category/Subcategory/ItemModel.
    Returns hierarchy_cache: {model_name: (category, subcategory, item_model)}.
    """
    category_name = category_name.strip()
    subcategory_name = subcategory_name.strip()
    model_names = {r.get('model_name', '').strip() for r in results if r.get('model_name')}
    now = timezone.now()

    # --- Prefetch existing category/subcategory ---
    categories = {
        c.name.lower(): c
        for c in Category.objects.filter(name__iexact=category_name)
    }
    subcategories = {
        s.name.lower(): s
        for s in Subcategory.objects.filter(name__iexact=subcategory_name)
    }

    # --- Ensure category ---
    category = categories.get(category_name.lower())
    if not category:
        category = Category.objects.create(name=category_name)
        categories[category_name.lower()] = category

    # --- Ensure subcategory ---
    subcategory = subcategories.get(subcategory_name.lower())
    if not subcategory:
        subcategory = Subcategory.objects.create(name=subcategory_name, category=category)
        subcategories[subcategory_name.lower()] = subcategory
    elif subcategory.category_id != category.id:
        subcategory.category = category
        subcategory.save(update_fields=['category'])

    # --- Preload item models for this subcategory ---
    existing_models = {
        m.name.lower(): m
        for m in ItemModel.objects.filter(subcategory=subcategory, name__in=model_names)
    }

    # --- Bulk create missing ones ---
    missing_models = [
        ItemModel(subcategory=subcategory, name=m)
        for m in model_names if m.lower() not in existing_models
    ]
    if missing_models:
        ItemModel.objects.bulk_create(missing_models)
        for m in missing_models:
            existing_models[m.name.lower()] = m

    # --- Build hierarchy cache ---
    hierarchy_cache = {
        m_name: (category, subcategory, existing_models[m_name.lower()])
        for m_name in model_names
    }

    return hierarchy_cache

import time
from django.db import IntegrityError



@csrf_exempt
@require_POST
def save_overnight_scraped_data(request):
    """Accepts payload from Node scraper and populates ItemModels, MarketItems, and CompetitorListings safely in batches."""
    import math
    start_time = time.time()
    print("🚀 [START] save_overnight_scraped_data")

    BATCH_MARKETITEM_CREATE = 200
    BATCH_LISTING_CREATE = 100
    BATCH_LISTING_UPDATE = 100
    BATCH_HISTORY_CREATE = 100

    try:
        reset_queries()

        # Step 0: Parse JSON
        data = json.loads(request.body.decode('utf-8'))
        category_name = data.get('category_name', '').strip()
        subcategory_name = data.get('subcategory_name', '').strip()
        results = data.get('results', [])

        if not results:
            return JsonResponse({'success': False, 'error': 'No results to process'})

        now = timezone.now()
        created_count = updated_count = history_count = 0

        # Step 1: Resolve hierarchy
        hierarchy_cache = ensure_hierarchy(category_name, subcategory_name, results)
        # Normalize keys in hierarchy_cache
        hierarchy_cache = {k.strip(): v for k, v in hierarchy_cache.items()}

        # Step 2: Precompute MarketItem keys
        market_item_keys = {}
        for variant in results:
            item_name = variant.get('item_name', '').strip()
            model_name = variant.get('model_name', '').strip()
            if not item_name or not model_name:
                continue
            if model_name not in hierarchy_cache:
                print(f"⚠️ Model not found in hierarchy_cache: '{model_name}'")
                continue
            category, subcategory, item_model = hierarchy_cache[model_name]
            key = (item_name, category.id, item_model.id)
            market_item_keys[key] = (item_name, category, item_model)

        # Step 3: Fetch existing MarketItems
        q_filter = Q()
        for title, category, item_model in market_item_keys.values():
            q_filter |= Q(title=title, category=category)
        existing_items_qs = MarketItem.objects.filter(q_filter)
        existing_items = {
            (mi.title.strip(), mi.category_id, mi.item_model_id): mi
            for mi in existing_items_qs
        }

        # Step 4: Bulk create missing MarketItems
        to_create = [
            MarketItem(title=title, category=category, item_model=item_model, last_scraped=now)
            for key, (title, category, item_model) in market_item_keys.items()
            if key not in existing_items
        ]
        for i in range(0, len(to_create), BATCH_MARKETITEM_CREATE):
            chunk = to_create[i:i+BATCH_MARKETITEM_CREATE]
            created_items = MarketItem.objects.bulk_create(chunk, ignore_conflicts=True)
            for mi in created_items:
                existing_items[(mi.title.strip(), mi.category_id, mi.item_model_id)] = mi

        # Step 5: Update last_scraped timestamps
        for mi in existing_items.values():
            mi.last_scraped = now
        MarketItem.objects.bulk_update(existing_items.values(), ['last_scraped'], batch_size=BATCH_MARKETITEM_CREATE)

        # Step 6: Prepare CompetitorListings
        all_market_items = list(existing_items.values())
        existing_listings_qs = CompetitorListing.objects.filter(
            market_item__in=all_market_items
        ).only('market_item_id', 'competitor', 'stable_id', 'price', 'trade_voucher_price', 'trade_cash_price')
        existing_listings = {
            (listing.market_item_id, listing.competitor.strip(), listing.stable_id.strip()): listing
            for listing in existing_listings_qs.iterator()
        }

        # Step 7: Process variants
        listings_to_create, listings_to_update, histories_to_create = [], [], []

        for variant in results:
            item_name = variant.get('item_name', '').strip()
            model_name = variant.get('model_name', '').strip()
            if not item_name or not model_name:
                continue
            if model_name not in hierarchy_cache:
                continue
            category, subcategory, item_model = hierarchy_cache[model_name]
            market_item = existing_items.get((item_name, category.id, item_model.id))
            if not market_item:
                continue

            for item in variant.get('listings', []):
                competitor = item.get('competitor', '').strip()
                stable_id = item.get('stable_id', '').strip()
                if not competitor or not stable_id:
                    continue

                key = (market_item.id, competitor, stable_id)
                price = float(item.get('price', 0) or 0)
                trade_voucher = item.get('tradeVoucher')
                trade_cash = item.get('tradeCash')

                title = item.get('title', '').strip()
                description = item.get('description', '').strip()
                condition = item.get('condition', '').strip()
                store = item.get('store', '').strip()
                url = item.get('url', '').strip()

                if key in existing_listings:
                    listing = existing_listings[key]
                    changed = (
                        price != listing.price or
                        trade_voucher != listing.trade_voucher_price or
                        trade_cash != listing.trade_cash_price
                    )
                    listing.price = price
                    listing.trade_voucher_price = trade_voucher
                    listing.trade_cash_price = trade_cash
                    listing.title = title
                    listing.description = description
                    listing.condition = condition
                    listing.store_name = store
                    listing.url = url
                    listing.is_active = True
                    listing.last_seen = now
                    listings_to_update.append(listing)

                    if changed:
                        histories_to_create.append(
                            CompetitorListingHistory(
                                listing=listing,
                                price=price,
                                trade_voucher_price=trade_voucher,
                                trade_cash_price=trade_cash,
                                title=title,
                                condition=condition,
                                timestamp=now
                            )
                        )
                else:
                    listings_to_create.append(
                        CompetitorListing(
                            market_item=market_item,
                            competitor=competitor,
                            stable_id=stable_id,
                            price=price,
                            trade_voucher_price=trade_voucher,
                            trade_cash_price=trade_cash,
                            title=title,
                            description=description,
                            condition=condition,
                            store_name=store,
                            url=url,
                            is_active=True,
                            last_seen=now
                        )
                    )

        # Step 8: Bulk write
        def batched_bulk_create(model, objects, batch_size):
            for i in range(0, len(objects), batch_size):
                chunk = objects[i:i+batch_size]
                with transaction.atomic():
                    model.objects.bulk_create(chunk, batch_size=batch_size, ignore_conflicts=True)

        def batched_bulk_update(model, objects, fields, batch_size):
            for i in range(0, len(objects), batch_size):
                chunk = objects[i:i+batch_size]
                with transaction.atomic():
                    model.objects.bulk_update(chunk, fields, batch_size=batch_size)

        batched_bulk_create(CompetitorListing, listings_to_create, BATCH_LISTING_CREATE)
        created_count = len(listings_to_create)

        batched_bulk_update(CompetitorListing, listings_to_update, [
            'price', 'trade_voucher_price', 'trade_cash_price',
            'title', 'description', 'condition', 'store_name',
            'url', 'is_active', 'last_seen'
        ], BATCH_LISTING_UPDATE)
        updated_count = len(listings_to_update)

        batched_bulk_create(CompetitorListingHistory, histories_to_create, BATCH_HISTORY_CREATE)
        history_count = len(histories_to_create)

        total_time = time.time() - start_time
        print(f"🏁 [END] save_overnight_scraped_data completed in {total_time:.2f}s")

        return JsonResponse({
            'success': True,
            'created': created_count,
            'updated': updated_count,
            'histories': history_count,
            'duration_seconds': round(total_time, 2)
        })

    except Exception as e:
        print(f"❌ Fatal error in save_overnight_scraped_data: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


def repricer_view(request):
    listings = (
        CompetitorListing.objects
        .annotate(history_count=Count('history'))
        .filter(history_count__gt=1)
        .select_related('market_item')
    )

    # Custom competitor order
    competitor_order = ["CashGenerator", "CashConverters", "CEX", "eBay"]

    # Sort listings according to competitor order
    listings = sorted(
        listings,
        key=lambda l: competitor_order.index(l.competitor)
        if l.competitor in competitor_order else len(competitor_order)
    )

    repricer_data = []
    for listing in listings:
        price_history = (
            listing.history.order_by('timestamp')
            .values_list('price', flat=True)
        )
        price_chain = " → ".join([f"£{p:.2f}" for p in price_history])

        repricer_data.append({
            'competitor': listing.competitor,
            'title': listing.title,
            'url': listing.url,
            'price_chain': price_chain,
            'current_price': listing.price,
        })

    return render(request, 'analysis/repricer.html', {'repricer_data': repricer_data})

def scraper_view(request):
    """Render the scrape iPhones page."""
    return render(request, "scraper.html")

from django.core.serializers.json import DjangoJSONEncoder
import json


def buyer_view(request):
    """Render the buyer page."""
    categories = Category.objects.all()
    return render(request, "analysis/buyer.html", {
            "categories": json.dumps(list(categories.values("id", "name")), cls=DjangoJSONEncoder)
        })

from dal import autocomplete
class CategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Category.objects.all()
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs

class SubcategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Subcategory.objects.all()
        category_id = self.forwarded.get('category', None)
        if category_id:
            qs = qs.filter(category_id=category_id)
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs

class ItemModelAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = ItemModel.objects.all()
        subcat_id = self.forwarded.get('subcategory', None)
        if subcat_id:
            qs = qs.filter(subcategory_id=subcat_id)
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs
