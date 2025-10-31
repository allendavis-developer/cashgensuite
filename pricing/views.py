from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db import transaction
from django.db.models import Q, Prefetch, Count
from django.utils import timezone

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

from pricing.utils.ai_utils import client
from pricing.utils.ai_utils import call_gemini_sync, generate_price_analysis, generate_bulk_price_analysis
from pricing.utils.competitor_utils import get_competitor_data
from pricing.utils.analysis_utils import process_item_analysis, save_analysis_to_db
from pricing.utils.search_term import build_search_term
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


def get_market_item(search_term):
    """Retrieve a market item by exact title match."""
    return MarketItem.objects.filter(title__iexact=search_term).first()

def determine_base_price(market_item):
    """Determine the base price based on competitor listings."""
    competitor_priority = ["CashGenerator", "CashConverters", "CEX", "eBay"]

    cash_gen_listings = list(
        CompetitorListing.objects.filter(
            market_item=market_item, competitor="CashGenerator", is_active=True
        ).order_by("price")
    )
    cash_conv_listings = list(
        CompetitorListing.objects.filter(
            market_item=market_item, competitor="CashConverters", is_active=True
        ).order_by("price")
    )

    # Case 1: Both competitors have listings
    if cash_gen_listings and cash_conv_listings:
        combined = sorted(cash_gen_listings + cash_conv_listings, key=lambda x: x.price)
        base_price = combined[2].price if len(combined) >= 3 else combined[-1].price
        return base_price, "Combined_CashGen_CashConv"

    # Case 2: Fallback to individual competitors
    for competitor in competitor_priority:
        qs = CompetitorListing.objects.filter(
            market_item=market_item, competitor=competitor, is_active=True
        )
        qs = qs.order_by("id") if competitor == "CEX" else qs.order_by("price")

        if qs.exists():
            listings = list(qs)
            if competitor == "CEX":
                base_price = listings[0].price * 0.85
            else:
                base_price = listings[2].price if len(listings) >= 3 else listings[-1].price
            return base_price, competitor

    return None, None

def round_down_to_even(value):
    """Round down to the nearest even integer."""
    return (int(value) // 2) * 2

import requests
# TODO: it might be worth batching this in the future with the overnight scraping.
def fetch_cex_cash_price(stable_id):
    """
    Fetch the CeX cash price for a given stable_id.
    Returns the cash price if found, otherwise None.
    """
    if not stable_id:
        return None

    url = f"https://wss2.cex.uk.webuy.io/v3/boxes/{stable_id}/detail"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/118.0.5993.117 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.cex.uk/",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        box = data.get("response", {}).get("data", {}).get("boxDetails", [{}])[0]
        return box.get("cashPrice")
    except Exception as e:
        print(f"CeX price lookup failed for {stable_id}: {e}")
        return None


def compute_prices_from_cex_rule(market_item, cex_rule=None):
    """
    Compute selling and buying prices from MarketItem using the cex_pct rule.
    Compute buying range: start = 50% of selling, end = CeX cash price if available, else 67% of selling.
    If no cex_rule is provided, use 20% less than CeX sale price.
    """
    if cex_rule:
        selling_price = round(market_item.cex_sale_price * cex_rule.cex_pct)
    else:
        selling_price = round(market_item.cex_sale_price * 0.8)

    buying_start_price = round(selling_price / 2)
    buying_end_price = market_item.cex_cash_trade_price or round(selling_price * 0.67)

    # sometimes buying start price is greater than the cex price so this will that issue
    if buying_start_price > buying_end_price:
        buying_start_price = round(buying_end_price * 0.8) 

    cex_url = market_item.cex_url if market_item.cex_url else None

    return selling_price, buying_start_price, buying_end_price, market_item.cex_cash_trade_price, market_item.cex_sale_price, cex_url




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
        attributes = data.get("attributes", {})

        if not category or not model:
            return JsonResponse({"success": False, "error": "Category and model are required."})

        search_term = build_search_term(model, category, attributes)
        market_item = get_market_item(search_term)
        print("Searching for:", search_term, "Found:", market_item)

        if not market_item:
            return JsonResponse({"success": False, "error": "No matching market item found."})

        # Get most specific CeX pricing rule
        cex_rule = get_most_specific_cex_rule(category_id, subcategory_id, model_id)

        if not market_item.cex_sale_price:
            return JsonResponse({"success": False, "error": "No CeX sale price available for this item."})

        selling_price, buying_start, buying_end, cex_buying_price, cex_selling_price, cex_url = compute_prices_from_cex_rule(
            market_item, cex_rule
        )

        return JsonResponse({
            "success": True,
            "search_term": search_term,
            "selling_price": selling_price,
            "buying_start_price": buying_start,
            "buying_end_price": buying_end,
            "cex_buying_price": cex_buying_price,
            "cex_selling_price": cex_selling_price,
            "cex_url": cex_url,
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

        # --- Fetch CeX cash price for the first active CEX listing ---
        cex_listing = CompetitorListing.objects.filter(
            competitor="CEX",
            market_item=market_item,
            is_active=True
        ).order_by("id").first()

        if cex_listing:
            # Save the sale price from the first CEX listing
            market_item.cex_sale_price = cex_listing.price
            market_item.cex_url = f"https://uk.webuy.com/product-detail?id={cex_listing.stable_id}"
            if cex_listing.stable_id:
                cex_cash_trade_price = fetch_cex_cash_price(cex_listing.stable_id)
                if cex_cash_trade_price is not None:
                    market_item.cex_cash_trade_price = cex_cash_trade_price
                    print(f"Updated market_item.cex_cash_trade_price to {cex_cash_trade_price}")

            market_item.save()
            print(f"Updated market_item.cex_sale_price to {cex_listing.price}")


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


# TODO: Move this to somewhere else, shouldn't be in your view.
class CompetitorAnalyzer:
    """Analyzes competitor data to generate strategic references"""
    
    @staticmethod
    def analyze(competitors):
        """
        Extract useful statistics from competitor data.
        Returns dict with highest, lowest, median, average, range_str, etc.
        """
        if not competitors:
            return None
        
        prices = [c.get("price", 0) for c in competitors if c.get("price", 0) > 0]
        if not prices:
            return None
        
        sorted_prices = sorted(prices)
        shops = [c.get("competitor", "Competitor") for c in competitors]
        
        return {
            'highest': max(prices),
            'lowest': min(prices),
            'average': sum(prices) / len(prices),
            'median': sorted_prices[len(sorted_prices) // 2],
            'second_highest': sorted_prices[-2] if len(sorted_prices) > 1 else sorted_prices[-1],
            'range_str': f"£{min(prices):.2f}-£{max(prices):.2f}",
            'highest_shop': shops[prices.index(max(prices))] if shops else "Competitor",
            'count': len(prices),
            'all_prices': sorted_prices
        }
    
    @staticmethod
    def format_reference(competitors, context="opening"):
        """Generate context-appropriate competitor reference with specific shop names and prices"""
        stats = CompetitorAnalyzer.analyze(competitors)
        
        if not stats:
            return "• Mention that Cash Generator and Cash Converters sell similar items and you need to compete with them."
        
        # Get individual shop prices for specific callouts
        shop_prices = {}
        for comp in competitors:
            shop = comp.get("competitor", "")
            price = comp.get("price", 0)
            if shop and price > 0:
                if shop not in shop_prices:
                    shop_prices[shop] = []
                shop_prices[shop].append(price)
        
        # Average prices per shop if multiple listings
        shop_averages = {shop: sum(prices)/len(prices) for shop, prices in shop_prices.items()}
        
        if context == "opening":
            # Use highest as strong anchor with specific shop
            return f"• Reference that {stats['highest_shop']} sells similar items at around £{stats['highest']:.2f}."
        
        elif context == "explanation":
            # List specific competitors and their prices
            if len(shop_averages) == 1:
                shop, price = list(shop_averages.items())[0]
                return f"• Show them that {shop} sells similar items at £{price:.2f}, and explain you need to compete with them."
            elif len(shop_averages) >= 2:
                shop_list = ", ".join([f"{shop} at £{price:.2f}" for shop, price in sorted(shop_averages.items(), key=lambda x: x[1], reverse=True)])
                return f"• Show them specific competitor prices: {shop_list}. Explain you need to compete with these shops."
            else:
                return f"• Explain competitor pricing ranges from {stats['range_str']} and you need to stay competitive."
        
        elif context == "mid":
            # Show 1-2 specific competitors
            if len(shop_averages) >= 2:
                sorted_shops = sorted(shop_averages.items(), key=lambda x: x[1], reverse=True)
                top_two = sorted_shops[:2]
                shop_refs = " and ".join([f"{shop} at £{price:.2f}" for shop, price in top_two])
                return f"• Reference that {shop_refs}. Remind them you need to compete with these prices."
            elif len(shop_averages) == 1:
                shop, price = list(shop_averages.items())[0]
                return f"• Mention that {shop} sells similar items at £{price:.2f} and you're pricing to compete."
            else:
                return f"• Reference competitor pricing at {stats['range_str']}."
        
        elif context == "maximum":
            # Show top competitor pricing
            if len(shop_averages) >= 1:
                highest_shop, highest_price = max(shop_averages.items(), key=lambda x: x[1])
                return f"• Point out that top competitor pricing (like {highest_shop} at £{highest_price:.2f}) factors into your maximum."
            else:
                return f"• Reference top competitor pricing around £{stats['second_highest']:.2f}."
        
        return f"• Mention competitor pricing ranges from {stats['range_str']}."


class NegotiationTemplates:
    """Enhanced negotiation templates with data-driven competitor references"""

    @staticmethod
    def get_opening_response(item_name, next_offer, competitors):
        """Opening response - always use highest competitor as anchor"""
        comp_ref = CompetitorAnalyzer.format_reference(competitors, context="opening")
        
        lines = [
            f"• Greet customer and acknowledge the {item_name}",
            comp_ref,
            "• Explain you offer around a quarter of brand new value for quick cash purchases",
            f"• Present your opening offer of **£{next_offer:.2f}**",
            "• Mention there's room to negotiate"
        ]
        
        return lines

    @staticmethod
    def get_explanation_response(item_name, current_offer, competitors):
        """Detailed explanation when customer asks 'why' - show full data"""
        comp_ref = CompetitorAnalyzer.format_reference(competitors, context="explanation")
        
        lines = [
            "• Acknowledge their question positively",
            comp_ref,
            "• Explain you base offers on roughly a quarter of brand new value",
            "• Mention the costs: refurb, testing, storage time",
            "• Be transparent: explain you typically sell at about slightly less than   double what you pay",
            f"• Reiterate the current offer is **£{current_offer:.2f}**",
            "• Emphasise you're giving cash today while being realistic"
        ]
        
        return lines

    @staticmethod
    def get_mid_negotiation_response(item_name, next_offer, last_offer, competitors):
        """Mid-negotiation response when customer rejects - use median pricing"""
        comp_ref = CompetitorAnalyzer.format_reference(competitors, context="mid")
        increase = next_offer - last_offer
        
        lines = [
            "• Show empathy and willingness to work with them",
            comp_ref,
            "• Remind them about refurb, testing, and time to sell costs",
            f"• Present your increased offer of **£{next_offer:.2f}** (up £{increase:.2f})",
            "• Frame it as meeting them partway"
        ]
        
        return lines

    @staticmethod
    def get_maximum_response(item_name, next_offer, competitors):
        """Maximum offer response - use 2nd highest competitor, full transparency"""
        comp_ref = CompetitorAnalyzer.format_reference(competitors, context="maximum")
        
        lines = [
            f"• Thank them for working with you on the {item_name}",
            comp_ref,
            "• Be completely transparent: explain you'd sell at roughly double to cover overheads",
            f"• Present your absolute maximum of **£{next_offer:.2f}**",
            "• Emphasize this is as high as you can go, ask if they can agree"
        ]
        
        return lines

    @staticmethod
    def get_accept_response(final_offer):
        """Customer accepted the offer"""
        return [
            f"• Express enthusiasm and confirm the deal at **£{final_offer:.2f}** cash",
            "• Thank them for working with you and frame it as fair for both sides"
        ]

    @staticmethod
    def get_decline_response():
        """Customer declined at maximum - polite close"""
        return [
            "• Be understanding and non-pushy",
            "• Let them know the offer stands if they change their mind",
            "• Encourage them to shop around and return if interested"
        ]

    @staticmethod
    def get_customer_reply_options(next_offer):
        """Generate the 3 button options for customer"""
        return [
            f"Yes — I'll take £{next_offer:.2f}",
            "No — that's too low",
            "Why — how did you price that?"
        ]


def detect_intent(customer_text):
    """Detect intent from button text only"""
    if not customer_text:
        return None
    
    txt = customer_text.lower()
    
    if "yes" in txt and "take" in txt:
        return "accept"
    if "why" in txt and "how" in txt:
        return "ask_reason"
    if "no" in txt and "too low" in txt:
        return "reject_low"
    
    # Default fallback
    return "reject_low"


def determine_increment(last_offer, max_price):
    """
    Determine realistic negotiation increments based on item value.
    Increments scale with price to feel natural.
    """
    price_range = max_price - last_offer

    # Scale increments by item value
    if max_price < 30:
        base = 2
    elif max_price < 80:
        base = 5
    elif max_price < 150:
        base = 10
    elif max_price < 400:
        base = 20
    elif max_price < 1000:
        base = 25
    else:
        base = 50

    # Never exceed remaining gap
    increment = min(base, price_range)
    
    return round(increment)


@csrf_exempt
@require_POST
def negotiation_step(request):
    """
    Enhanced Cash Generator Negotiation Engine
    - Data-driven competitor references
    - Transparent pricing explanation
    - Simple 3-button interaction (Yes/No/Why)
    """
    try:
        data = json.loads(request.body)
        item_name = (data.get("item_name") or "").strip()
        buying_range = data.get("buying_range") or {}
        competitors = data.get("selected_competitor_rows") or []
        conversation_history = data.get("conversation_history") or []

        print(competitors)

        if not item_name or not buying_range:
            return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

        min_price = float(buying_range.get("min", 0))
        max_price = float(buying_range.get("max", 0))

        if min_price <= 0 or max_price <= 0 or min_price > max_price:
            return JsonResponse({"success": False, "error": "Invalid buying range"}, status=400)

        # --- Determine latest customer intent ---
        intent = None
        if conversation_history:
            latest_customer_text = conversation_history[-1].get("customer", "")
            intent = detect_intent(latest_customer_text)

        # --- Offer progression ---
        last_offer = None
        at_maximum = False
        next_offer = float(min_price)

        if conversation_history:
            last_offer = conversation_history[-1].get("assistant_offer")
            last_offer = float(last_offer) if last_offer is not None else None

        # Determine next offer based on intent
        if intent == "accept" and last_offer is not None:
            # Customer accepted - freeze at last offer
            next_offer = last_offer
            at_maximum = True
        elif intent == "ask_reason" and last_offer is not None:
            # Customer asking why - keep same offer
            next_offer = last_offer
        elif last_offer is None:
            # First interaction - start at minimum
            next_offer = float(min_price)
        else:
            # Customer rejected - increment offer
            gap = max_price - last_offer
            if gap > 0:
                increment = determine_increment(last_offer, max_price)
                increment = min(increment, gap)
                next_offer = last_offer + increment
            else:
                next_offer = last_offer
            
            # Check if we've reached maximum
            at_maximum = (next_offer >= max_price)
            next_offer = min(next_offer, max_price)

        # Calculate progress for UI
        progress = round(((next_offer - min_price) / (max_price - min_price) * 100), 1) if max_price > min_price else 100.0

        # --- Build response lines based on state ---
        if not conversation_history:
            # Opening response
            response_lines = NegotiationTemplates.get_opening_response(item_name, next_offer, competitors)
        
        elif intent == "accept":
            # Customer accepted
            response_lines = NegotiationTemplates.get_accept_response(next_offer)
        
        elif intent == "ask_reason":
            # Customer asked why
            response_lines = NegotiationTemplates.get_explanation_response(item_name, next_offer, competitors)
        
        elif intent == "reject_low":
            if at_maximum:
                # At maximum - final offer
                response_lines = NegotiationTemplates.get_maximum_response(item_name, next_offer, competitors)
            else:
                # Mid-negotiation - increment and explain
                response_lines = NegotiationTemplates.get_mid_negotiation_response(item_name, next_offer, last_offer, competitors)
        
        else:
            # Fallback (shouldn't happen)
            response_lines = [f"• Current offer: **£{next_offer:.2f}**"]

        # Prepare customer reply options
        customer_replies = NegotiationTemplates.get_customer_reply_options(next_offer)

        # Convert to HTML for frontend
        formatted_response_html = "<br>".join(response_lines)

        response_data = {
            "your_response": formatted_response_html,
            "your_response_bullets": response_lines,
            "customer_reply_options": customer_replies,
            "suggested_offer": f"£{next_offer:.2f}",
            "at_maximum": at_maximum,
            "negotiation_progress": progress,
            "intent_detected": intent
        }

        return JsonResponse({
            "success": True, 
            "ai_response": response_data, 
            "at_maximum": at_maximum
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
