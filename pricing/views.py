from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db import transaction
from django.db.models import Q, Prefetch, Count
from django.utils import timezone
from django.db import connection, reset_queries
from django.db import IntegrityError

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

@csrf_exempt
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
    return MarketItem.objects.filter(title__icontains=search_term).first()

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

    # let's fetch the cc listings dynamically now
    

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


import requests

def fetch_cex_box_details(stable_id):
    """
    Fetch raw CeX data for a box ID.

    Returns:
        {
            "out_of_stock": bool,
            "price": float or None,
            "cash_trade_price": float or None,
            "url": str or None,
        }
        or None on failure.
    """
    url = f"https://wss2.cex.uk.webuy.io/v3/boxes/{stable_id}/detail"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/118.0.5993.117 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.cex.uk/",
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        box = data.get("response", {}).get("data", {}).get("boxDetails", [{}])[0]
        return {
            "out_of_stock": box.get("outOfStock"),
            "price": box.get("sellPrice"),
            "last_price_updated_date": box.get("lastPriceUpdatedDate"),
            "cash_trade_price": box.get("cashPrice"),
            "url": f"https://uk.webuy.com/product-detail?id={stable_id}",
        }

    except Exception as e:
        print(f"CeX price lookup failed for {stable_id}: {e}")
        return None




def classify_mover(cex_sale_price, cex_cash_trade_price):
    if not cex_sale_price or not cex_cash_trade_price:
        return "unknown", "Not enough data to classify mover."

    margin = (cex_sale_price - cex_cash_trade_price) / cex_sale_price

    if margin > 0.50:
        return "slow", "High CeX margin (>50%), typically indicates slow-moving stock."
    elif margin >= 0.40:
        return "medium", "CeX margin between 40–50%, typical of medium movers."
    else:
        return "fast", "Low CeX margin (<40%), usually fast-moving stock."

def find_cex_rule(category, subcategory, item_model, movement_class):
    if movement_class == "unknown":
        allrules = CEXPricingRule.objects.filter(
            is_active=True,
            movement_class="medium",
        )
        return allrules.filter(
            category__isnull=True,
            subcategory__isnull=True,
            item_model__isnull=True
        ).first()

    qs = CEXPricingRule.objects.filter(
        is_active=True,
        movement_class=movement_class,
    )

    # 1. Most specific: category + subcategory + item_model
    rule = qs.filter(
        category=category,
        subcategory=subcategory,
        item_model=item_model
    ).first()
    if rule:
        return rule

    # 2. Less specific: category + subcategory (no item_model)
    rule = qs.filter(
        category=category,
        subcategory=subcategory,
        item_model__isnull=True
    ).first()
    if rule:
        return rule

    # 3. category only
    rule = qs.filter(
        category=category,
        subcategory__isnull=True,
        item_model__isnull=True
    ).first()
    if rule:
        return rule

    # 4. default rule (no category / subcategory / item_model)
    return qs.filter(
        category__isnull=True,
        subcategory__isnull=True,
        item_model__isnull=True
    ).first()



def compute_prices_from_cex_rule(
    cex_sale_price,
    cex_cash_trade_price,
    cex_url,
    out_of_stock,
    category=None,
    subcategory=None,
    item_model=None
):
    # 1. Determine movement class via classify_mover
    movement_class, movement_reason = classify_mover(
        cex_sale_price,
        cex_cash_trade_price
    )

    # 2. Fetch the correct rule using your specificity ladder
    cex_rule = find_cex_rule(
        category=category,
        subcategory=subcategory,
        item_model=item_model,
        movement_class=movement_class
    )

    print(cex_rule)

    # 3. If out of stock, bail early
    # if out_of_stock:
    #     return {
    #         "selling_price": 0,
    #         "buying_start_price": 0,
    #         "buying_mid_price": 0,
    #         "buying_end_price": 0,
    #         "category": "medium",
    #         "cex_trade_cash_price": cex_cash_trade_price,
    #         "cex_sale_price": cex_sale_price,
    #         "cex_url": cex_url,
    #         "reasons": {
    #             "selling_price": "Out of stock on CEX, we shouldn't take this item in",
    #             "buying_start_price": "Out of stock on CEX, we shouldn't take this item in",
    #             "buying_mid_price": "Out of stock on CEX, we shouldn't take this item in",
    #             "buying_end_price": "Out of stock on CEX, we shouldn't take this item in",
    #             "category": movement_reason,
    #         },
    #     }

    # 4. Selling price logic
    if cex_rule:
        selling_price = round(cex_sale_price * cex_rule.cex_pct)
        reason_selling = (
            f"Applied CeX rule ({cex_rule.cex_pct * 100:.0f}%) "
            "based on detected movement class."
        )
    else:
        selling_price = round(cex_sale_price * 0.8)
        reason_selling = "Used default 20% discount (no rule found)."

    # 5. Buying logic
    cex_margin = (cex_sale_price - cex_cash_trade_price) / cex_sale_price
    target_profit = round(selling_price * cex_margin)
    buying_start_price = selling_price - target_profit

    buying_end_price = cex_cash_trade_price or round(selling_price / 2)

    if buying_start_price > buying_end_price and cex_rule:
        buying_start_price = round(buying_end_price * cex_rule.cex_pct)
        reason_buying_start = (
            f"Applied CeX buying rule ({cex_rule.cex_pct * 100:.0f}%)."
        )
    else:
        reason_buying_start = "Set to 50% of selling price."

    buying_mid_price = round((buying_start_price + buying_end_price) / 2)
    reason_buying_mid = "Average of start and end prices."
    reason_buying_end = (
        "Matched CeX cash trade price."
        if cex_cash_trade_price
        else "Used 50% of selling price (no CeX cash trade price available)."
    )

    return {
        "selling_price": selling_price,
        "category": movement_class,
        "buying_start_price": buying_start_price,
        "buying_mid_price": buying_mid_price,
        "buying_end_price": buying_end_price,
        "cex_trade_cash_price": cex_cash_trade_price,
        "cex_sale_price": cex_sale_price,
        "cex_url": cex_url,
        "cex_rrp_pct": cex_rule.cex_pct,
        "reasons": {
            "selling_price": reason_selling,
            "buying_start_price": reason_buying_start,
            "buying_mid_price": reason_buying_mid,
            "buying_end_price": reason_buying_end,
            "category": movement_reason,
        },
    }

@csrf_exempt
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

        search_term = build_search_term(model, category, subcategory, attributes)
        market_item = get_market_item(search_term)
        print("Searching for:", search_term, "Found:", market_item)

        if not market_item:
            return JsonResponse({"success": False, "error": "No matching market item found."})

        # url = cc_search_url(model, subcategory, category, attributes)
        # raw_cc_data = fetch_cc_search_results(url)
        # print(url)

        # # --- Parse It ---
        # parsed_results = parse_cashconverters_results(raw_cc_data)

        # # --- Save To Database (reuse your existing pipeline) ---
        # save_scraped_data_internal(
        #     item_name=search_term,
        #     category_id=category_id,
        #     model_id=model_id,
        #     attributes=attributes,
        #     results=parsed_results
        # )

        # print(parsed_results)


        competitor_stats = get_competitor_price_stats(market_item)

        # Get best CEX listing
        qs = CompetitorListing.objects.filter(
            competitor="CEX",
            market_item=market_item,
            is_active=True
        ).order_by("id")

        cex_listing = qs.filter(Q(title__icontains="unlocked")).first() or qs.first()

        if not cex_listing:
            return JsonResponse({
                "success": False,
                "error": "No CEX listing found."
            })

        # CEX scrape happens HERE now
        box_data = fetch_cex_box_details(cex_listing.stable_id)
        
        if not box_data:
            return JsonResponse({"success": False, "error": "Failed to fetch CeX box details"})
        

        # Extract values to pass into compute function
        out_of_stock = False
        if box_data["out_of_stock"] == 1:
            out_of_stock = True
        cex_sale_price = cex_listing.price or 0
        cex_cash_trade_price = cex_listing.trade_cash_price
        cex_url = cex_listing.url

        # Pure compute
        prices = compute_prices_from_cex_rule(
            cex_sale_price=cex_sale_price,
            cex_cash_trade_price=cex_cash_trade_price,
            cex_url=cex_url,
            out_of_stock=False,
            category=category_id,
            subcategory=subcategory_id,
            item_model=model_id
        )

        #format last price updated
        last_price_updated_date = box_data["last_price_updated_date"]
        if last_price_updated_date:
            datetime = box_data["last_price_updated_date"].split(" ")
            date = datetime[0]
            yyyymmdd = date.split("-")
            date_formatted = yyyymmdd[2] + "/" + yyyymmdd[1] + "/" + yyyymmdd[0]
        else:
            date_formatted = "N/A"

        # Send response
        return JsonResponse({
            "success": True,
            "search_term": search_term,
            "selling_price": prices["selling_price"],
            "buying_start_price": prices["buying_start_price"],
            "buying_mid_price": prices["buying_mid_price"],
            "buying_end_price": prices["buying_end_price"],
            "cex_buying_price": prices["cex_trade_cash_price"],
            "cex_selling_price": prices["cex_sale_price"],
            "category": prices["category"],
            "cex_url": prices["cex_url"],
            "competitor_stats": competitor_stats,
            "reasons": prices["reasons"],
            "cex_last_price_updated_date": date_formatted,
            "cex_rrp_pct": prices["cex_rrp_pct"],
            "out_of_stock": out_of_stock
        })

    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)



import urllib.parse

CC_CATEGORY_MAP = {
    "smartphones and mobile": "1073741966",
    "games (discs & cartridges)": "1073741887",
    "tablets": "1073741998",
    "laptops": "1073742012",
}


def cc_search_url(model=None, subcategory=None, category=None, attributes=None):
    """
    Build a Cash Converters search URL using:
        query = model + " " + all attribute values
    No query parameter is taken directly.
    """
    attributes = attributes or {}

    # Map category to CashConverters ID
    category_id = "all"
    if category:
        category_id = CC_CATEGORY_MAP.get(category.lower(), "all")

    # Build query text: "model attr1 attr2 ..."
    parts = []
    if model:
        parts.append(str(model))

    for val in attributes.values():
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())

    query_string = " ".join(parts)
    encoded_query = urllib.parse.quote(query_string)

    # Build final URL
    url = (
        "https://www.cashconverters.co.uk/c3api/search/results"
        "?Sort=default&page=1"
        f"&f%5Bcategory%5D%5B0%5D={category_id}"
        f"&f%5Blocations%5D%5B0%5D=all"
        f"&query={encoded_query}"
    )
    print("CC Search URL: ", url)
    return url

def fetch_cc_search_results(query):
    """
    Fetch raw search results from Cash Converters UK API using only a query string.
    Prints the JSON response for now.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/118.0.5993.117 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.cex.uk/",
    }

    try:
        response = requests.get(query, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        return None
    except ValueError:
        print("Failed to parse JSON response")
        return None

def parse_cashconverters_results(payload):
    """
    Convert CashConverters API JSON into the structure expected by save_scraped_data().
    Returns a list of dicts, each representing one competitor listing.
    """

    try:
        items = (
            payload.get("Value", {})
                  .get("ProductList", {})
                  .get("ProductListItems", [])
        )
    except Exception:
        return []

    parsed = []

    for raw in items:
        # CC fields (based on their typical structure)
        title = raw.get("Title", "")
        price = raw.get("Sp", 0)
        url = raw.get("Url", "")
        store = raw.get("StoreNameWithState", "") 
        condition = raw.get("Condition", "") or raw.get("ProductCondition", "")
        stable_id = raw.get("Code") 

        parsed.append({
            "competitor": "CashConverters",
            "stable_id": stable_id,
            "price": price,
            "title": title,
            "description": "",   
            "condition": condition,
            "store": store,
            "url": f"https://www.cashconverters.co.uk{url}" if url.startswith("/") else url
        })

    return parsed

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

        return JsonResponse({
            'success': True,
            'created': len(listings_to_create),
            'updated': len(listings_to_update),
            'histories': len(histories_to_create),
        })

    except Exception as e:
        print("❌ Error saving scraped data:", e)
        return JsonResponse({'success': False, 'error': str(e)})

def save_scraped_data_internal(item_name, category_id, model_id, attributes, results):
    fake_request_payload = {
        "item_name": item_name,
        "category": category_id,
        "item_model": model_id,
        "attributes": attributes,
        "results": results
    }

    fake_request = type("Req", (), {})()
    fake_request.body = json.dumps(fake_request_payload).encode("utf-8")
    fake_request.method = "POST"   # <-- REQUIRED for @require_POST

    return save_scraped_data(fake_request)


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
            # "options": a.options or []
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
            is_online=data.get("is_online", {})

            if not category or not model:
                return JsonResponse({"success": False, "error": "Category and model are required."}, status=400)

            # Build the search term - FIXED: model is the item_name
            search_term = build_search_term(model, category, subcategory, attributes, is_online=is_online)  
            
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
        response_data["combinations"] = variants["combinations"]


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

from django.db import connection, transaction
import time

@csrf_exempt
@require_POST
def save_overnight_scraped_data(request):
    start_time = time.time()
    print("🚀 [START] save_overnight_scraped_data")

    try:
        data = json.loads(request.body.decode('utf-8'))
        category_name = data.get('category_name')
        subcategory_name = data.get('subcategory_name')
        results = data.get('results', [])

        total_variants = len(results)
        print(f"📦 Processing {total_variants} variants")

        if not results:
            return JsonResponse({'success': False, 'error': 'No results'})

        now = timezone.now()
        created_count = 0
        updated_count = 0
        history_count = 0

        # --------------------------------------------------------------------
        # 1. Build hierarchy cache
        # --------------------------------------------------------------------
        print("📚 Building hierarchy cache...")
        hierarchy_cache = ensure_hierarchy(category_name, subcategory_name, results)
        print(f"✅ Cached {len(hierarchy_cache)} models")

        # --------------------------------------------------------------------
        # 2. Preload ALL needed MarketItems
        # --------------------------------------------------------------------
        print("🔍 Pre-fetching MarketItems...")

        all_item_names = {v.get('item_name').strip()
                          for v in results
                          if v.get('item_name')}

        existing_market_items = {}
        item_names_list = list(all_item_names)

        for i in range(0, len(item_names_list), 500):
            chunk = item_names_list[i:i+500]
            items = (
                MarketItem.objects
                .filter(title__in=chunk)
                .select_related('category', 'item_model')
            )
            for mi in items:
                existing_market_items[(mi.title, mi.category_id, mi.item_model_id)] = mi

        print(f"✅ Found {len(existing_market_items)} existing MarketItems")

        # --------------------------------------------------------------------
        # 3. Create any missing MarketItems
        # --------------------------------------------------------------------
        to_create = []

        for variant in results:
            item_name = variant.get('item_name')
            model_name = variant.get('model_name', '').strip()

            if not item_name or not model_name or model_name not in hierarchy_cache:
                continue

            category, subcategory, item_model = hierarchy_cache[model_name]
            key = (item_name.strip(), category.id, item_model.id)

            if key not in existing_market_items:
                to_create.append(
                    MarketItem(
                        title=item_name.strip(),
                        category=category,
                        item_model=item_model,
                        last_scraped=now
                    )
                )

        if to_create:
            print(f"🆕 Creating {len(to_create)} new MarketItems...")
            for i in range(0, len(to_create), 100):
                batch = MarketItem.objects.bulk_create(to_create[i:i+100])
                for mi in batch:
                    existing_market_items[(mi.title, mi.category_id, mi.item_model_id)] = mi

        # Update last_scraped
        all_items = []
        for i in range(0, len(item_names_list), 500):
            chunk = item_names_list[i:i+500]
            all_items.extend(MarketItem.objects.filter(title__in=chunk))

        for mi in all_items:
            mi.last_scraped = now

        for i in range(0, len(all_items), 200):
            MarketItem.objects.bulk_update(all_items[i:i+200], ['last_scraped'])

        # Rebuild definitive map
        existing_market_items = {
            (mi.title, mi.category_id, mi.item_model_id): mi
            for mi in all_items
        }

        print(f"✅ Total MarketItems ready: {len(existing_market_items)}")

        # --------------------------------------------------------------------
        # 4. Preload ALL existing listings once
        # --------------------------------------------------------------------
        print("📦 Preloading all existing competitor listings...")

        all_market_item_ids = {mi.id for mi in existing_market_items.values()}

        existing_listings = {}
        listing_qs = CompetitorListing.objects.filter(
            market_item_id__in=all_market_item_ids
        ).only(
            'id', 'market_item_id', 'competitor', 'stable_id',
            'price', 'trade_voucher_price', 'trade_cash_price'
        )

        for lst in listing_qs:
            key = (lst.market_item_id, lst.competitor, lst.stable_id)
            existing_listings[key] = lst

        print(f"✅ Loaded {len(existing_listings)} existing listings")

        # --------------------------------------------------------------------
        # 5. Process all variants in chunks, using global existing_listings map
        # --------------------------------------------------------------------
        CHUNK_SIZE = 200

        for chunk_idx in range(0, total_variants, CHUNK_SIZE):
            chunk_start = time.time()
            variant_chunk = results[chunk_idx:chunk_idx + CHUNK_SIZE]

            listings_to_create = []
            listings_to_update = []
            histories_to_create = []

            # per-chunk dedupe (avoid creating same row twice)
            seen_in_chunk = set()

            for variant in variant_chunk:
                item_name = variant.get('item_name')
                model_name = variant.get('model_name', '').strip()

                if not item_name or not model_name or model_name not in hierarchy_cache:
                    continue

                category, subcategory, item_model = hierarchy_cache[model_name]
                key_mi = (item_name.strip(), category.id, item_model.id)
                market_item = existing_market_items.get(key_mi)

                if not market_item:
                    continue

                for item in variant.get('listings', []):
                    competitor = item.get('competitor')
                    stable_id = item.get('stable_id')

                    if not competitor or not stable_id:
                        continue

                    lookup_key = (market_item.id, competitor, stable_id)

                    price = float(item.get('price', 0))
                    trade_voucher = item.get('tradeVoucher')
                    trade_cash = item.get('tradeCash')
                    title = item.get('title', '')
                    description = item.get('description', '')
                    condition = item.get('condition', '')
                    store = item.get('store', '')
                    url = item.get('url', '')

                    # skip duplicates inside same chunk
                    if lookup_key in seen_in_chunk:
                        continue
                    seen_in_chunk.add(lookup_key)

                    # ---- existing listing
                    if lookup_key in existing_listings:
                        listing = existing_listings[lookup_key]

                        price_changed = (
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

                        if price_changed:
                            histories_to_create.append(
                                CompetitorListingHistory(
                                    listing=listing,
                                    price=price,
                                    trade_voucher_price=trade_voucher,
                                    trade_cash_price=trade_cash,
                                    title=title,
                                    condition=condition,
                                    timestamp=now,
                                )
                            )
                        continue

                    # ---- new listing
                    new_listing = CompetitorListing(
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
                    listings_to_create.append(new_listing)

            # ----------------------------------------------------------------
            # Bulk create new listings
            # ----------------------------------------------------------------
            if listings_to_create:
                for i in range(0, len(listings_to_create), 100):
                    batch = listings_to_create[i:i+100]
                    created = CompetitorListing.objects.bulk_create(batch)
                    created_count += len(created)

                    # add to global existing_listings map
                    for lst in created:
                        key = (lst.market_item_id, lst.competitor, lst.stable_id)
                        existing_listings[key] = lst

                        histories_to_create.append(
                            CompetitorListingHistory(
                                listing=lst,
                                price=lst.price,
                                trade_voucher_price=lst.trade_voucher_price,
                                trade_cash_price=lst.trade_cash_price,
                                title=lst.title,
                                condition=lst.condition,
                                timestamp=now,
                            )
                        )

            # ----------------------------------------------------------------
            # Bulk update existing listings
            # ----------------------------------------------------------------
            if listings_to_update:
                for i in range(0, len(listings_to_update), 100):
                    CompetitorListing.objects.bulk_update(
                        listings_to_update[i:i+100],
                        [
                            'price', 'trade_voucher_price', 'trade_cash_price',
                            'title', 'description', 'condition', 'store_name',
                            'url', 'is_active', 'last_seen'
                        ]
                    )
                    updated_count += len(listings_to_update[i:i+100])

            # ----------------------------------------------------------------
            # Bulk create histories
            # ----------------------------------------------------------------
            if histories_to_create:
                for i in range(0, len(histories_to_create), 100):
                    CompetitorListingHistory.objects.bulk_create(
                        histories_to_create[i:i+100],
                        ignore_conflicts=True
                    )
                    history_count += len(histories_to_create[i:i+100])

            print(f"    Chunk {chunk_idx}-{chunk_idx + len(variant_chunk)} "
                  f"→ {len(listings_to_create)} created, "
                  f"{len(listings_to_update)} updated")

            connection.close_if_unusable_or_obsolete()

        total_time = time.time() - start_time
        print(f"\n🏁 Completed in {total_time:.2f}s")
        print(f"📊 Created: {created_count}, Updated: {updated_count}, Histories: {history_count}")

        return JsonResponse({
            'success': True,
            'created': created_count,
            'updated': updated_count,
            'histories': history_count,
            'total_variants': total_variants,
            'duration_seconds': round(total_time, 2)
        })

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        connection.close()
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
