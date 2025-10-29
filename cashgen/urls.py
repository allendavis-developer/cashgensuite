from django.contrib import admin
from django.urls import path
import pricing.views as v

urlpatterns = [
    # ----------------------------- PAGES -----------------------------
    path('', v.home_view, name='home'),
    path('admin/', admin.site.urls),
    path('individual-item-analyser/', v.individual_item_analyser_view, name='individual_item_analyser'),
    path('item-buying-analyser/', v.item_buying_analyser_view, name='item_buying_analyser'),
    path("inventory/free/", v.inventory_free_stock_view, name="inventory_free_stock"),
    path("repricer/", v.repricer_view, name="repricer"),
    path("scraper/", v.scraper_view, name="scraper"),
    path("buyer/", v.buyer_view, name="buyer"),

    # ------------------ CATEGORY AND GLOBAL RULES --------------------------------
    path("categories/", v.category_list, name="category_list"),
    path("categories/add/", v.add_category_view, name="add_category"),
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
    path("api/get-match-values/", v.get_match_value_choices, name="get_match_values"),

    # ----------------------------- API -----------------------------
    path("bulk-analysis", v.bulk_analysis, name='bulk_analysis'),
    path('save_listing/', v.save_listing, name='save_listing'),
    path("save_scraped_data/", v.save_scraped_data, name="save_scraped_data"),
    path('admin/get-models/', v.get_models, name='get_models'),

    path("api/generate_search_term/", v.generate_search_term, name="generate_search_term"),

    path("api/price-analysis/<int:analysis_id>/", v.price_analysis_detail, name="price_analysis_detail"),
    path("api/buying-range-analysis/", v.buying_range_analysis, name="buying_range_analysis"),
    path('api/negotiation-step/', v.negotiation_step, name='negotiation-step'),
    path('api/subcategorys/', v.subcategorys, name='api-subcategorys'),
    path('api/models/', v.models, name='api-models'),
    path('api/category_attributes/', v.category_attributes, name='api-category-attributes'),
    path('api/check_existing_items/', v.check_existing_items, name='api-check-existing-items'),
    path('api/get-selling-price/', v.get_selling_price, name='api-get-selling-price'),


     # Creation endpoints (allow adding new items)
    path('api/add_category/', v.add_category, name='api-add-category'),
    path('api/add_subcategory/', v.add_subcategory, name='api-add-subcategory'),
    path('api/add_model/', v.add_model, name='api-add-model'),
    path('api/add_attribute_option/', v.add_attribute_option, name='api-add-attribute-option'),
]

from django.conf import settings
from django.conf.urls.static import static


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
