from pricing.models import CompetitorListing

def get_competitor_data(item_title: str, include_url: bool = True) -> str:
    """
    Return a newline-separated string of competitor lines:
    "Competitor | Listing Title | £price | Store Name"
    If include_url=True, append the URL at the end.
    """
    if not item_title:
        return ""

    listings = CompetitorListing.objects.filter(market_item__title__icontains=item_title)
    lines = []
    for l in listings:
        price_str = f"£{l.price:.2f}" if l.price is not None else "N/A"
        store_str = l.store_name if l.store_name else "N/A"
        print(store_str)
        if include_url:
            url_str = l.url if l.url else "#"
            lines.append(f"{l.competitor} | {l.title} | {price_str} | {store_str} | {url_str}")
        else:
            lines.append(f"{l.competitor} | {l.title} | {price_str} | {store_str}")
    return "\n".join(lines)

def calculate_competitor_count(competitor_data):
    """Calculate number of competitors from competitor data"""
    if not competitor_data.strip():
        return 0
    return len(competitor_data.strip().split("\n"))
