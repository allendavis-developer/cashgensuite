from playwright.sync_api import sync_playwright

def scrape_stock():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = context.pages[0]

        page.goto("https://nospos.com/stock/search")

        # Grab all rows in the table
        rows = page.query_selector_all("tr[data-key]")

        all_products = []

        for row in rows:
            # Stock code is in the first <a> in the row
            stock_link_element = row.query_selector("td a")
            stock_code = stock_link_element.inner_text().strip() if stock_link_element else None
            stock_link = stock_link_element.get_attribute("href") if stock_link_element else None

            # Product name is in the <div> inside second <td>
            product_name_element = row.query_selector("td div.line-clamp-1.text-break")
            product_name = product_name_element.inner_text().strip() if product_name_element else None

            # Other info: price, quantity, date
            tds = row.query_selector_all("td")
            price = tds[2].inner_text().strip() if len(tds) > 2 else None
            retail_price = tds[3].inner_text().strip() if len(tds) > 3 else None
            quantity = tds[4].inner_text().strip() if len(tds) > 4 else None
            date = tds[5].inner_text().strip() if len(tds) > 5 else None

            all_products.append({
                "product_name": product_name,
                "stock_code": stock_code,
                "stock_link": stock_link,
                "price": price,
                "retail_price": retail_price,
                "quantity": quantity,
                "date": date
            })

        for item in all_products:
            print(item)

        browser.close()


def scrape_agreements():
    from playwright.sync_api import sync_playwright
    import json

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = context.pages[0]

        page.goto(
            "https://nospos.com/reports/buying/movedtofreestock?start_date=2025-09-08&end_date=2025-09-21&category=403%2C")

        # Find all agreement rows (they have the class pattern "agreement-XXXXX")
        agreement_rows = page.query_selector_all("tr.text-danger[style*='border-top: 3px solid #000']")

        agreements = []

        for row in agreement_rows:
            # Extract agreement number from the strong tag
            agreement_element = row.query_selector("strong")
            agreement_number = None
            if agreement_element:
                agreement_text = agreement_element.inner_text().strip()
                # Extract just the number from "Agreement #70015"
                agreement_number = agreement_text.replace("Agreement #",
                                                          "") if "Agreement #" in agreement_text else None

            # Get all table cells in this row
            cells = row.query_selector_all("td")

            created_date = None
            expiry_date = None
            previous_agreements = None

            # Parse the cells for created date, expiry date, and previous agreements
            for cell in cells:
                cell_text = cell.inner_text().strip()
                if "Created" in cell_text and len(cell_text.split()) == 1:  # Just "Created"
                    # Next cell should contain the date
                    next_cell = cells[cells.index(cell) + 1] if cells.index(cell) + 1 < len(cells) else None
                    if next_cell:
                        created_date = next_cell.inner_text().strip()
                elif "Expiry Date" in cell_text:
                    # Extract date from span with pull-right class
                    date_span = cell.query_selector("span.pull-right")
                    if date_span:
                        expiry_date = date_span.inner_text().strip()
                elif "Previous Agreements" in cell_text:
                    # Extract value from span with pull-right class
                    prev_span = cell.query_selector("span.pull-right")
                    if prev_span:
                        previous_agreements = prev_span.inner_text().strip()
                    else:
                        # If no span, it might be directly after "Previous Agreements"
                        previous_agreements = cell_text.replace("Previous Agreements", "").strip()

            # Now get the next row which should contain Created By, Customer, and Days Gone info
            next_row = row.query_selector("xpath=following-sibling::tr[1]")
            created_by = None
            customer = None
            days_gone_past_expiry = None

            if next_row:
                next_cells = next_row.query_selector_all("td")
                for cell in next_cells:
                    cell_text = cell.inner_text().strip()
                    if cell_text.startswith("Created By"):
                        # Next cell should contain the staff name
                        next_cell = next_cells[next_cells.index(cell) + 1] if next_cells.index(cell) + 1 < len(
                            next_cells) else None
                        if next_cell:
                            created_by = next_cell.inner_text().strip()
                    elif cell_text.startswith("Customer"):
                        # Next cell should contain customer info
                        next_cell = next_cells[next_cells.index(cell) + 1] if next_cells.index(cell) + 1 < len(
                            next_cells) else None
                        if next_cell:
                            customer = next_cell.inner_text().strip()
                    elif "Days Gone Pass Expiry" in cell_text:
                        # Next cell should contain the number
                        next_cell = next_cells[next_cells.index(cell) + 1] if next_cells.index(cell) + 1 < len(
                            next_cells) else None
                        if next_cell:
                            # Extract just the number before the span
                            days_text = next_cell.inner_text().strip()
                            days_gone_past_expiry = days_text.split()[0] if days_text else None

            # Get item details - look for rows with the same agreement class that contain item data
            items = []
            agreement_class = f"agreement-{agreement_number}"

            # Find all rows with the same agreement class
            if agreement_number:
                all_agreement_rows = page.query_selector_all(f"tr.{agreement_class}")

                for agreement_row in all_agreement_rows:
                    row_cells = agreement_row.query_selector_all("td")
                    # Skip header rows (they have th elements) and info rows
                    if len(row_cells) >= 6 and not agreement_row.query_selector("th"):
                        # Check if this looks like an item row (has item description, barcode, prices, etc.)
                        first_cell_text = row_cells[0].inner_text().strip()
                        # Skip rows that are clearly not item rows
                        if (first_cell_text and
                                not first_cell_text.startswith("Created By") and
                                not first_cell_text.startswith("Customer") and
                                not first_cell_text.startswith("Days Gone") and
                                not first_cell_text.startswith("Agreement #") and
                                len(first_cell_text) > 3):  # Reasonable item description length

                            # Extract all item details
                            item = {
                                "description": first_cell_text,
                                "barcode": row_cells[1].inner_text().strip() if len(row_cells) > 1 else None,
                                "rrp": row_cells[2].inner_text().strip() if len(row_cells) > 2 else None,
                                "item_cost": row_cells[3].inner_text().strip() if len(row_cells) > 3 else None,
                                "quantity": row_cells[4].inner_text().strip() if len(row_cells) > 4 else None,
                                "clock_moved_to_free_date": None
                            }

                            # Extract clock and moved to free date from the 6th cell
                            if len(row_cells) > 5:
                                cell_text = row_cells[5].inner_text().strip()
                                # Split by the span to get clock and date
                                parts = cell_text.split()
                                if parts:
                                    item["clock"] = parts[0]  # First part should be the clock number
                                    # Get the date from the span with pull-right class
                                    date_span = row_cells[5].query_selector("span.pull-right")
                                    if date_span:
                                        item["moved_to_free_date"] = date_span.inner_text().strip()

                            items.append(item)

            agreements.append({
                "agreement_number": agreement_number,
                "created_date": created_date,
                "expiry_date": expiry_date,
                "previous_agreements": previous_agreements,
                "created_by": created_by,
                "customer": customer,
                "days_gone_past_expiry": days_gone_past_expiry,
                "items": items
            })

        print(f"Found {len(agreements)} agreements:")
        for agreement in agreements:
            print(agreement)

        # Save to JSON file
        with open('../../agreements_data.json', 'w', encoding='utf-8') as f:
            json.dump(agreements, f, indent=2, ensure_ascii=False)

        print(f"\nData saved to agreements_data.json")

        browser.close()


scrape_agreements()