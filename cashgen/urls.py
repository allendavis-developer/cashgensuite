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
    path("bulk-analysis", v.bulk_analysis, name='bulk_analysis'),
    path("generate-search-term/", v.generate_search_term, name="generate_search_term"),
    path('save_listing/', v.save_listing, name='save_listing'),
    path("save_scraped_data/", v.save_scraped_data, name="save_scraped_data"),
    path('admin/get-models/', v.get_models, name='get_models'),

    path("api/price-analysis/<int:analysis_id>/", v.price_analysis_detail, name="price_analysis_detail"),
    path("api/buying-range-analysis/", v.buying_range_analysis, name="buying_range_analysis"),
    path('api/negotiation-step/', v.negotiation_step, name='negotiation-step'),
    path('api/manufacturers/', v.manufacturers, name='api-manufacturers'),
    path('api/models/', v.models, name='api-models'),
    path('api/category_attributes/', v.category_attributes, name='api-category-attributes'),

     # Creation endpoints (allow adding new items)
    path('api/add_category/', v.add_category, name='api-add-category'),
    path('api/add_manufacturer/', v.add_manufacturer, name='api-add-manufacturer'),
    path('api/add_model/', v.add_model, name='api-add-model'),
    path('api/add_attribute_option/', v.add_attribute_option, name='api-add-attribute-option'),
]
