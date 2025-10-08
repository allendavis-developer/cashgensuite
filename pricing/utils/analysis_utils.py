from django.http import JsonResponse
from django.utils import timezone

from pricing.models import MarketItem, CompetitorListing, PriceAnalysis, InventoryItem
from .competitor_utils import calculate_competitor_count, get_competitor_data
from .price_utils import calculate_confidence, parse_price_from_response
from .ai_utils import generate_price_analysis


def process_item_analysis(data):
    """Main processing logic for item analysis that can be reused across screens"""
    # Extract and clean data
    item_name = (data.get("item_name") or "").strip()
    description = (data.get("description") or "").strip()
    urgency = int(data.get("urgency", 3))  # Add this line, default to 3

    # Check if frontend already sent local scrape data
    local_scrape_data = data.get("local_scrape_data")

    if local_scrape_data:
        print("Using local scraper data from browser")

        # Update DB directly from local_scrape_data
        if isinstance(local_scrape_data, list):

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
                        store_name=entry.get("store") or "N/A",
                        url=entry.get("url", "#")
                    )
                )

            # Single database hit for all listings
            CompetitorListing.objects.bulk_create(listings_to_create, ignore_conflicts=True)

            competitor_data_for_ai = get_competitor_data(item_name, False)
            competitor_data_for_frontend = get_competitor_data(item_name, True)

    # Generate AI analysis
    ai_response, reasoning, suggested_price = generate_price_analysis(
        item_name, description, competitor_data_for_ai, urgency  # Add urgency parameter
    )

    # Remove any existing PriceAnalysis for this InventoryItem
    inventory_item, _ = InventoryItem.objects.get_or_create(title=item_name)

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


def save_analysis_to_db(item_name, description, reasoning, suggested_price, competitor_data, cost_price=None):
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

    # Build defaults dict
    defaults = {
        "reasoning": reasoning,
        "suggested_price": decimal_price,
        "confidence": calculate_confidence(competitor_count),
        "created_at": timezone.now()
    }

    # Include cost_price if provided
    if cost_price is not None:
        defaults["cost_price"] = cost_price


    # Save analysis
    analysis, created = PriceAnalysis.objects.update_or_create(
        item=inventory_item,
        defaults=defaults
    )

    return {
        "competitor_count": competitor_count,
        "analysis_id": analysis.id
    }
