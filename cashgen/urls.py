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

    # ----------------------------- API -----------------------------
    path("bulk-analysis", v.bulk_analysis, name='bulk_analysis'),
    path('save_listing/', v.save_listing, name='save_listing'),
    path("save_scraped_data/", v.save_scraped_data, name="save_scraped_data"),
    path('admin/get-models/', v.get_models, name='get_models'),

    path("api/generate_search_term/", v.generate_search_term, name="generate_search_term"),

    path("api/buying-range-analysis/", v.buying_range_analysis, name="buying_range_analysis"),
    path('api/negotiation-step/', v.negotiation_step, name='negotiation-step'),
    path('api/subcategorys/', v.subcategorys, name='api-subcategorys'),
    path('api/models/', v.models, name='api-models'),
    path('api/category_attributes/', v.category_attributes, name='api-category-attributes'),
    path('api/categories/', v.categories, name='api-categories'),

    path('api/check_existing_items/', v.check_existing_items, name='api-check-existing-items'),
    path('api/get-selling-and-buying-price/', v.get_selling_and_buying_price, name='api-get-selling-and-buying-price'),
    path('api/get-scrape-sources-for-category/', v.get_scrape_sources_for_category, name='api-get-scrape-sources-for-category'),

     # Creation endpoints (allow adding new items)
    path('api/add_category/', v.add_category, name='api-add-category'),
    path('api/add_subcategory/', v.add_subcategory, name='api-add-subcategory'),
    path('api/add_model/', v.add_model, name='api-add-model'),
    path('api/add_attribute_option/', v.add_attribute_option, name='api-add-attribute-option'),


    path('category-autocomplete/', v.CategoryAutocomplete.as_view(), name='category-autocomplete'),
    path('subcategory-autocomplete/', v.SubcategoryAutocomplete.as_view(), name='subcategory-autocomplete'),
    path('itemmodel-autocomplete/', v.ItemModelAutocomplete.as_view(), name='itemmodel-autocomplete'),

]

from django.conf import settings
from django.conf.urls.static import static


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
