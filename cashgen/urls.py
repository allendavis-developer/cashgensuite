from django.contrib import admin
from django.urls import path
import pricing.views as v

urlpatterns = [
    # ----------------------------- PAGES -----------------------------
    path('', v.home_view, name='home'),
    path('admin/', admin.site.urls),
    path('individual-item-analysis/', v.individual_item_analysis_view, name='individual_item_analysis'),
    path('individual-item-analyser/', v.individual_item_analyser_view, name='individual_item_analyser'),
    path('item-buying-analyser/', v.item_buying_analyser_view, name='item_buying_analyser'),
    path("inventory/free/", v.inventory_free_stock_view, name="inventory_free_stock"),

    # ------------------ CATEGORY AND GLOBAL RULES --------------------------------
    path("categories/", v.category_list, name="category_list"),
    path("categories/add/", v.add_category, name="add_category"),
    path("categories/<int:pk>/", v.category_detail, name="category_detail"),
    path("categories/<int:pk>/edit/", v.edit_category, name="edit_category"),
    path("categories/<int:pk>/delete/", v.delete_category, name="delete_category"),
    path("categories/<int:pk>/manage/", v.manage_category, name="manage_category"),

    path("global-rules/add/", v.add_global_rule, name="add_global_rule"),
    path("global-rules/<int:pk>/edit/", v.edit_global_rule, name="edit_global_rule"),
    path("global-rules/<int:pk>/delete/", v.delete_global_rule, name="delete_global_rule"),


    path("rules/add/<int:category_pk>/", v.add_rule, name="add_rule"),
    path("rules/<int:pk>/edit/", v.edit_rule, name="edit_rule"),
    path("rules/<int:pk>/delete/", v.delete_rule, name="delete_rule"),

    # ----------------------------- API -----------------------------
    path('marketitem_suggestions', v.marketitem_suggestions, name='marketitem_suggestions'),
    path('link_inventory_to_marketitem/', v.link_inventory_to_marketitem, name='link_inventory_to_marketitem'),
    path('unlink_inventory_from_marketitem/', v.unlink_inventory_from_marketitem, name='unlink_inventory_from_marketitem'),
    path('launch-playwright-listing/', v.launch_playwright_listing, name='launch_playwright_listing'),
    path('update_marketitem_keywords/', v.update_marketitem_keywords, name='update_marketitem_keywords'),
    path("bulk-analysis", v.bulk_analysis, name='bulk_analysis'),
    path('scan-barcodes/', v.scan_barcodes, name='scan_barcodes'),
    path('bulk-analyse-items/', v.bulk_analyse_items, name='bulk_analyse_items'),
    path("api/price-analysis/<int:analysis_id>/", v.price_analysis_detail, name="price_analysis_detail"),
    path('scrape-nospos/', v.scrape_nospos_view, name='scrape_nospos_view'),
    path('detect_irrelevant_competitors/', v.detect_irrelevant_competitors, name='detect_irrelevant_competitors'),
    path("api/buying-range-analysis/", v.buying_range_analysis, name="buying_range_analysis"),

]
