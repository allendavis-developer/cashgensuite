import pytest
import json
from unittest.mock import patch
from django.urls import reverse
from django.test import Client
from pricing.models import InventoryItem, MarketItem, PriceAnalysis, CompetitorListing
from decimal import Decimal

# -----------------------------
# Utility fixtures
# -----------------------------
@pytest.fixture
def client():
    return Client()

@pytest.fixture
def inventory_item(db):
    return InventoryItem.objects.create(title="Test Phone", description="Testing")

@pytest.fixture
def market_item(db):
    return MarketItem.objects.create(title="Apple iPhone 15")

@pytest.fixture
def competitor_listing(db, market_item):
    return CompetitorListing.objects.create(
        market_item=market_item,
        competitor="CashConverters",
        title="iPhone 15 - Good Condition",
        price=299.99,
        store_name="Main Street",
        url="https://example.com/listing"
    )

@pytest.fixture
def price_analysis(db, inventory_item):
    return PriceAnalysis.objects.create(
        item=inventory_item,
        reasoning="Test reasoning",
        suggested_price=199.99,
        confidence=80
    )


# -----------------------------
# Tests for link_inventory_to_marketitem
# -----------------------------
@pytest.mark.django_db
def test_link_inventory_creates_new_marketitem(client, inventory_item):
    payload = {
        "inventory_title": "Test Phone",
        "marketitem_title": "Some New Market Item"
    }
    url = reverse("link_inventory_to_marketitem")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["linked_inventory"] == "Test Phone"
    assert data["linked_market_item"] == "Some New Market Item"
    assert data["created_new_marketitem"] is True


@pytest.mark.django_db
def test_link_inventory_existing_marketitem(client, inventory_item, market_item):
    payload = {
        "inventory_title": "Test Phone",
        "marketitem_title": "Apple iPhone 15"
    }
    url = reverse("link_inventory_to_marketitem")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["linked_inventory"] == "Test Phone"
    assert data["linked_market_item"] == "Apple iPhone 15"
    assert data["created_new_marketitem"] is False # Ensure we did not create a new market item


# -----------------------------
# Tests for unlink_inventory_from_marketitem
# -----------------------------
@pytest.mark.django_db
def test_unlink_inventory(client, inventory_item, market_item):
    inventory_item.market_item = market_item
    inventory_item.save()

    payload = {"inventory_title": "Test Phone", "marketitem_title": "Apple iPhone 15"}
    url = reverse("unlink_inventory_from_marketitem")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")

    assert response.status_code == 200
    assert response.json()["success"] is True
    inventory_item.refresh_from_db()
    assert inventory_item.market_item is None


@pytest.mark.django_db
def test_unlink_inventory_not_linked(client, inventory_item):
    payload = {"inventory_title": "Test Phone"}
    url = reverse("unlink_inventory_from_marketitem")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")
    assert response.status_code == 400
    assert response.json()["success"] is False


# -----------------------------
# Tests for marketitem_suggestions
# -----------------------------
@pytest.mark.django_db
def test_marketitem_suggestions(client, market_item):
    url = reverse("marketitem_suggestions") + "?q=iphone"
    response = client.get(url)
    data = response.json()

    assert response.status_code == 200
    assert "Apple iPhone 15" in data["suggestions"]
    assert data["count"] == 1


# -----------------------------
# Tests for price_analysis_detail
# -----------------------------
@pytest.mark.django_db
def test_price_analysis_detail(client, inventory_item):
    analysis = PriceAnalysis.objects.create(
        item=inventory_item,
        reasoning="Test reasoning",
        suggested_price=199.99,
        confidence=80
    )
    url = reverse("price_analysis_detail", args=[analysis.id])
    response = client.get(url)
    data = response.json()

    print(data)

    assert response.status_code == 200
    assert data["success"] is True
    assert data["analysis_id"] == analysis.id
    assert data["item_title"] == "Test Phone"
    assert data["suggested_price"] == "199.99"
    assert "reasoning" in data


@pytest.mark.django_db
def test_individual_item_analyser_post_creates_analysis(client: Client):
    payload = {"item_name": "Test Phone", "description": "Test description"}

    # Mock both the AI call and the scraper
    with patch("pricing.views.call_gemini_sync") as mock_ai, \
            patch("pricing.views.scrape_all_competitors") as mock_scraper:
        # AI returns fixed response
        mock_ai.return_value = "Test reasoning\nFINAL:£199.99"

        # Scraper does nothing
        mock_scraper.return_value = None

        url = reverse("individual_item_analyser")
        response = client.post(url, data=payload, content_type="application/json")

        assert response.status_code == 200
        data = response.json()
        assert data["success"]
        assert "suggested_price" in data
        assert PriceAnalysis.objects.filter(item__title="Test Phone").exists()

        # Ensure the scraper was called
        mock_scraper.assert_called_once_with("Test Phone")


def test_individual_item_analyser_get_renders_template(client: Client):
    url = reverse("individual_item_analyser")
    response = client.get(url)
    assert response.status_code == 200
    assert "individual_item_analyser.html" in [t.name for t in response.templates]


@pytest.mark.django_db
def test_bulk_analyse_items(client: Client):
    payload = {"items": [{"name": "Bulk Phone", "description": "desc"}]}

    with patch("pricing.views.call_gemini_sync") as mock_ai, \
         patch("pricing.views.scrape_all_competitors") as mock_scrape:
        mock_ai.return_value = "Reasoning bulk\nFINAL:£299.99"
        mock_scrape.return_value = None

        url = reverse("bulk_analyse_items")
        response = client.post(url, data=payload, content_type="application/json")
        assert response.status_code == 200
        data = response.json()
        assert data["success"]
        assert len(data["results"]) == 1
        assert PriceAnalysis.objects.filter(item__title="Bulk Phone").exists()


@pytest.mark.django_db
def test_scrape_nospos_view(client: Client):
    payload = {"barcodes": ["123", "456"]}

    with patch("pricing.views.scrape_barcodes") as mock_scrape:
        mock_scrape.return_value = [{"barcode": "123"}, {"barcode": "456"}]
        url = reverse("scrape_nospos_view")
        response = client.post(url, data=payload, content_type="application/json")
        data = response.json()
        assert data["success"]
        assert isinstance(data.get("products", []), list)


@pytest.mark.django_db
def test_launch_playwright_listing_success(client: Client):
    payload = {"item_name": "Phone", "description": "Desc", "price": "199.99", "serial_number": "SN123"}

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Success"
        mock_run.return_value.stderr = ""
        url = reverse("launch_playwright_listing")
        response = client.post(url, data=payload, content_type="application/json")
        data = response.json()
        assert data["success"]


@pytest.mark.django_db
def test_launch_playwright_listing_failure(client: Client):
    payload = {"item_name": "Phone", "description": "Desc", "price": "199.99", "serial_number": "SN123"}

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Error"
        url = reverse("launch_playwright_listing")
        response = client.post(url, data=payload, content_type="application/json")
        data = response.json()
        assert not data["success"]
        assert "Automation failed" in data["error"]


@pytest.mark.django_db
def test_update_marketitem_keywords(client: Client):
    market_item = MarketItem.objects.create(title="TestMarket")
    payload = {"marketitem_title": "TestMarket", "exclude_keywords": "badword"}

    url = reverse("update_marketitem_keywords")
    response = client.post(url, data=payload, content_type="application/json")
    data = response.json()
    assert data["success"]
    market_item.refresh_from_db()
    assert market_item.exclude_keywords == "badword"


@pytest.mark.django_db
def test_link_inventory_with_exclude_keywords(client, inventory_item):
    """Test linking inventory with exclude keywords"""
    payload = {
        "inventory_title": "Test Phone",
        "marketitem_title": "New Market Item",
        "exclude_keywords": "broken damaged"
    }
    url = reverse("link_inventory_to_marketitem")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True

    # Check that MarketItem was created with exclude_keywords
    market_item = MarketItem.objects.get(title="New Market Item")
    assert market_item.exclude_keywords == "broken damaged"



@pytest.mark.django_db
def test_individual_item_analyser_with_existing_competitor_data(client, competitor_listing):
    """Test individual item analyzer when competitor data already exists"""
    payload = {
        "item_name": "Apple iPhone 15",
        "description": "Test iPhone description"
    }

    with patch("pricing.views.call_gemini_sync") as mock_ai:
        mock_ai.return_value = "Based on competitor data\nFINAL:£299.99"

        url = reverse("individual_item_analyser")
        response = client.post(url, data=json.dumps(payload), content_type="application/json")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["competitor_count"] == 1
        assert "CashConverters" in data["competitor_data"]


@pytest.mark.django_db
def test_individual_item_analyser_invalid_json(client):
    """Test handling of invalid JSON"""
    url = reverse("individual_item_analyser")
    response = client.post(url, data="invalid json", content_type="application/json")

    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False


@pytest.mark.django_db
def test_individual_item_analyser_get_with_prefilled_data(client):
    """Test GET request with prefilled URL parameters"""
    url = reverse("individual_item_analyser") + "?item=TestItem&description=TestDesc"
    response = client.get(url)

    assert response.status_code == 200
    assert "individual_item_analyser.html" in [t.name for t in response.templates]
    assert response.context["prefilled_item"] == "TestItem"
    assert response.context["prefilled_description"] == "TestDesc"


@pytest.mark.django_db
def test_price_analysis_detail_not_found(client):
    """Test price analysis detail for non-existent analysis"""
    url = reverse("price_analysis_detail", args=[999])
    response = client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_bulk_analyse_empty_items(client):
    """Test bulk analysis with empty items list"""
    payload = {"items": []}
    url = reverse("bulk_analyse_items")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")

    data = response.json()
    assert data["success"] is False
    assert "No items provided" in data["error"]


@pytest.mark.django_db
def test_bulk_analyse_missing_item_name(client):
    """Test bulk analysis with missing item name"""
    payload = {"items": [{"description": "desc", "barcode": "123"}]}

    with patch("pricing.views.call_gemini_sync"), \
            patch("pricing.views.scrape_all_competitors"):
        url = reverse("bulk_analyse_items")
        response = client.post(url, data=json.dumps(payload), content_type="application/json")

        data = response.json()
        assert data["success"] is True
        assert len(data["results"]) == 1
        assert data["results"][0]["success"] is False
        assert "Missing item name" in data["results"][0]["error"]


@pytest.mark.django_db
def test_bulk_analyse_with_market_item(client, market_item):
    """Test bulk analysis using MarketItem for search"""
    payload = {
        "items": [{
            "name": "iPhone 15 Pro",
            "description": "desc",
            "market_item": "Apple iPhone 15",
            "cost_price": "£200"
        }]
    }

    with patch("pricing.views.call_gemini_sync") as mock_ai, \
            patch("pricing.views.scrape_all_competitors") as mock_scrape:
        mock_ai.return_value = "COST PRICE was :£200\nReasoning\nFINAL:£299.99"
        mock_scrape.return_value = None

        url = reverse("bulk_analyse_items")
        response = client.post(url, data=json.dumps(payload), content_type="application/json")

        data = response.json()
        assert data["success"] is True
        assert data["results"][0]["search_query_used"] == "Apple iPhone 15"


# -----------------------------
# New tests for uncovered views
# -----------------------------
@pytest.mark.django_db
def test_bulk_analysis_view(client):
    """Test bulk analysis template view"""
    url = reverse("bulk_analysis")
    response = client.get(url)

    assert response.status_code == 200
    assert "bulk_analysis.html" in [t.name for t in response.templates]


@pytest.mark.django_db
def test_individual_item_analysis_view(client):
    """Test individual item analysis template view"""
    url = reverse("individual_item_analysis")
    response = client.get(url)

    assert response.status_code == 200
    assert "individual_item_analysis.html" in [t.name for t in response.templates]


@pytest.mark.django_db
def test_scan_barcodes_success(client):
    """Test scan barcodes endpoint success"""
    payload = {"barcodes": ["123456789", "987654321"]}

    with patch("pricing.views.scrape_barcodes") as mock_scrape:
        mock_scrape.return_value = [
            {"barcode": "123456789", "name": "Product 1"},
            {"barcode": "987654321", "name": "Product 2"}
        ]

        url = reverse("scan_barcodes")
        response = client.post(url, data=json.dumps(payload), content_type="application/json")

        data = response.json()
        assert data["success"] is True
        assert len(data["products"]) == 2


@pytest.mark.django_db
def test_scan_barcodes_no_barcodes(client):
    """Test scan barcodes with no barcodes provided"""
    payload = {"barcodes": []}

    url = reverse("scan_barcodes")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")

    data = response.json()
    assert data["success"] is False
    assert "No barcodes provided" in data["error"]


@pytest.mark.django_db
def test_scan_barcodes_get_method(client):
    """Test scan barcodes with GET method (should fail)"""
    url = reverse("scan_barcodes")
    response = client.get(url)

    assert response.status_code == 405
    data = response.json()
    assert data["success"] is False
    assert "POST request required" in data["error"]

# -----------------------------
# Edge case and error handling tests
# -----------------------------
@pytest.mark.django_db
def test_marketitem_suggestions_empty_query(client):
    """Test market item suggestions with empty query"""
    url = reverse("marketitem_suggestions") + "?q="
    response = client.get(url)
    data = response.json()

    assert response.status_code == 200
    assert data["suggestions"] == []
    assert data["count"] == 0


@pytest.mark.django_db
def test_unlink_inventory_invalid_json(client):
    """Test unlink inventory with invalid JSON"""
    url = reverse("unlink_inventory_from_marketitem")
    response = client.post(url, data="invalid json", content_type="application/json")

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "Invalid JSON" in data["error"]


@pytest.mark.django_db
def test_launch_playwright_missing_fields(client):
    """Test playwright launch with missing required fields"""
    payload = {"item_name": "Phone"}  # Missing description and price

    url = reverse("launch_playwright_listing")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")

    data = response.json()
    assert data["success"] is False
    assert "Missing required fields" in data["error"]


@pytest.mark.django_db
def test_launch_playwright_timeout(client):
    """Test playwright launch timeout"""
    payload = {
        "item_name": "Phone",
        "description": "Desc",
        "price": "£199.99",
        "serial_number": "SN123"
    }

    with patch("subprocess.run") as mock_run:
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("cmd", 300)

        url = reverse("launch_playwright_listing")
        response = client.post(url, data=json.dumps(payload), content_type="application/json")

        data = response.json()
        assert data["success"] is False
        assert "timed out" in data["error"]


@pytest.mark.django_db
def test_update_marketitem_keywords_not_found(client):
    """Test updating keywords for non-existent MarketItem"""
    payload = {
        "marketitem_title": "Nonexistent Item",
        "exclude_keywords": "test"
    }

    url = reverse("update_marketitem_keywords")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "MarketItem not found" in data["error"]


# -----------------------------
# Integration-style tests
# -----------------------------
@pytest.mark.django_db
def test_full_analysis_workflow(client):
    """Test complete workflow: create item -> analyze -> check analysis"""
    # Step 1: Analyze item
    payload = {"item_name": "Workflow Phone", "description": "Test workflow"}

    with patch("pricing.views.call_gemini_sync") as mock_ai, \
            patch("pricing.views.scrape_all_competitors"):
        mock_ai.return_value = "Analysis reasoning\nFINAL:£399.99"

        url = reverse("individual_item_analyser")
        response = client.post(url, data=json.dumps(payload), content_type="application/json")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    # Step 2: Check that analysis was saved
    analysis = PriceAnalysis.objects.get(item__title="Workflow Phone")
    assert analysis.suggested_price == Decimal('399.99')

    # Step 3: Retrieve analysis detail
    url = reverse("price_analysis_detail", args=[analysis.id])
    response = client.get(url)
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["item_title"] == "Workflow Phone"
