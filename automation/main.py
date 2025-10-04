from scraper_utils import save_prices

if __name__ == "__main__":
    summary = save_prices("CashConverters", "iphone 15 256gb", exclude=["pro"])
    print("CashConverter iPhone 15 256GB:", summary)

    summary = save_prices("CashGenerator", "iphone 15 256gb", exclude=["pro"])
    print("CashGenerator iPhone 15 256GB:", summary)

    summary = save_prices("CEX", "iphone 15 256gb", exclude=["pro"])
    print("CEX iPhone 15 256GB:", summary)

    summary = save_prices("eBay", "iphone 15 256gb", exclude=["pro"])
    print("eBay iPhone 15 256GB:", summary)
