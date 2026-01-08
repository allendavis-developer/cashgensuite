[33m462738b[m[33m ([m[1;36mHEAD[m[33m -> [m[1;32mmain[m[33m, [m[1;31morigin/main[m[33m, [m[1;31morigin/HEAD[m[33m)[m restart button
[33m381aa06[m C:\dev2\cashgensuite\.venv\Scripts\activate.bat
[33m921f8fa[m refactor ebay modal code in buyer to a seperate file ebay.html
[33m4f9c8ac[m frontend small change
[33m801e981[m overview page
[33meb2ca39[m cex buyer
[33mb04f6d9[m making progress
[33mfcebb7e[m Prevent Tom Select from vertically centering
[33m56df3b2[m Progress
[33m4fdecd5[m Intermediate step -> halfway working cex tool within deep research
[33m35d0c93[m Include cex.html
[33m4704f7e[m research wizard
[33m09c9dfd[m modal
[33mea8d2a0[m searching through game barcode
[33m7456914[m suggested rrp + offer
[33mda86ed5[m ebay buyer displays suggested rrp
[33m062fe58[m add item modal + db  search terms imrpoved for new system
[33md157d45[m ebay buyer improving
[33m2c44390[m progress
[33md821ecb[m ebay shows images
[33mb06f01d[m ebay buyer improvemnets
[33mb9b9a19[m improve display of filter and build ebay url
[33mf89223a[m ebay filters showing up beautifully on buyer
[33m81662a6[m realised we don't need the extension to get the ebay filters and ebay has a json backend for htis
[33mac8d8da[m ebay filters are collapsible
[33m8c10f64[m ebay items in buyer: start
[33me772693[m improvements
[33m205538e[m buyer has new feature: add from cex url
[33m1b660ca[m Improvements
[33mcb03c8c[m display rrp
[33m490622c[m frontend for more sophisticated ebay filtering
[33m390ba50[m Improvements
[33m497fdac[m mode
[33m890fcce[m min margin to 20%
[33m497cc99[m More hotfixes
[33m50b90f3[m confirm and list btns do not round rrps anymore
[33ma2251a6[m hotfixes
[33m28db5fc[m hotfixes
[33m7a65c32[m set it up so that cex mode can change if u rescrape
[33m3f8c7ef[m use cex price from box data instead of db
[33me93ba62[m fix issue with a | in the title throwing off the competitor table and causing prices to display incorrectly
[33m8980d0d[m min margin
[33mf3ffd6a[m switcher
[33m03b3225[m thinamajig
[33md319332[m improvements
[33mc677d50[m ebay mode
[33m560001a[m improvements
[33m91e94a5[m remove cp + min margin from market summary + more qol
[33md3d8eb9[m cex price
[33m030cb19[m improvements
[33m37a5fbc[m improve
[33m375a73c[m hotfix
[33m1b6c4d6[m fix issue with model not prefilling, now attributs need prefilling
[33m00b8295[m change some text
[33m3b6cedc[m added st helens
[33m845a8e0[m tom select for individual item analyser
[33m1642f54[m  cursors progress
[33m6b05bb7[m fetching and parsing cc results
[33m63dce7a[m workin on cc url builder
[33ma44e0a5[m improvements
[33m99b62cd[m improve display of data
[33m6f2da43[m click to reveal functionality on max offer
[33m6b07619[m set max offer at 28% margin (will be changable later)
[33mcd882dc[m bug fixes
[33meac1d8b[m frontend improvements
[33md4c71af[m buyer has more data
[33me1dc121[m idk
[33mc80a315[m ensure save_overnight_scraped_data creates histories
[33m325f49b[m improve buyer add loading spinner
[33mac06a2e[m remove analyse button
[33mcf96aeb[m manual offer
[33m9d9d570[m fetch cex if out of stock or not
[33m53428fa[m analyse as soon as thing is added
[33m654bb3c[m various qol changes
[33mdc66ace[m improve modal
[33mc395a7e[m improve layout buyer
[33m63d0f89[m current offer mid offer starting offer final offer
[33m7c01131[m default rule -- when u don't fill in category or anything in cex pricing rule
[33m81737dc[m fix csrf cookie
[33m9df6680[m change market item searches to contains
[33m53d4deb[m improve save_overnight_scraped_data
[33m4dd6d1f[m individual item analyser now uses the new searching system
[33m43b6f88[m idk
[33m3cc69a0[m only load the appropriate attributes
[33mb54d2f4[m bulk update listings in chunk
[33m69de64e[m cleanup
[33me888b34[m cleanup + fixes
[33mca2b76d[m stop fetching cex prices dynamically
[33mae23d22[m improve ui buyer
[33m53635c9[m go back to dynamic fetching cex sale price as necessary
[33m75cd19c[m bulk update done
[33mfa5ccb4[m batch scrape
[33mdff9efe[m connection to overnight scraper
[33me5d9b17[m saving using subcategory too now
[33m775073a[m move add model on top of table
[33mff94541[m default select is cg
[33m8e1af82[m remove openai dependencies
[33mde4d524[m mode changed to show frequency/total
[33me288893[m Reorder table columns
[33m62b447d[m seperate out buying range into two cells
[33md437d71[m Cleanup
[33m3c3593d[m cleanup and fixes
[33m4b75125[m  added fallback for when buying start price happens to be greater than the cex trade in for cash price
[33m6076d24[m fix issue where it asked you to add models multiple times when u pressed it once
[33ma906cfc[m save cex price, url, and buying price to db when scraping
[33m340bd22[m display cex price on buyer page
[33mb4c8e91[m remove freestock view
[33m9dbc0dc[m remove global margin rule form and category form from the old rules page
[33m3537201[m Remove the global and margin rules page since we have a beautiful admin page now
[33m21afc33[m admin styling
[33m04d4bcd[m cex pricing rule admin
[33meef13c0[m remove price analysis model
[33m7eda1a6[m cex pricing rule model
[33mc72c0ec[m cex trade in cash price be end of the buying range
[33mef46dd4[m refactor get_selling_or_buying_price
[33m57f64b6[m better add item modal
[33mc43170e[m analyse all button + be the third cheapest in cc and cg
[33m5d285b5[m analyse all button
[33me290e02[m bug fixes
[33m819e3fd[m undo the cleanup and chain the scraping to the analysis
[33md1ce308[m cleanup buyer.html file redo
[33m3c0363a[m cleanup buyer.html file
[33mcc0beb2[m scrape by sources in category table
[33m5bc698b[m add a field to select category wise scrape sources and allow the users to add new models from the bulk buying page
[33m251945a[m display price as buying range
[33m3e54938[m improve styling of buyer page
[33mc8c40bf[m get buying price in buyer
[33mc5cc65f[m get selling price
[33m099a24d[m quick bug fix~
[33m4a0537a[m cleanup and bug fixes
[33m92cb9b0[m buyer page scrapes items now
[33mcb42005[m Add item modal in buyer page js code moved to static file
[33mecb3f58[m auto select the third item in the range
[33m24cb6a6[m small cleanup
[33mfc0ccf0[m replace manufacturer with subcategory everywhere in code
[33m8330b39[m remove scraped nospos data input fields from buying analyser
[33m10b9b00[m remove confirm and list button from buying in page
[33m30e8901[m buyer 2.0 bulk page connected to old buyer
[33m0b0f67c[m rename instances of manufacturer to subcategory in frontend
[33m61f8833[m bulk buyer page
[33mbdba132[m modal input for buyer
[33md547d7a[m buyer frontend: add quantity input and details and remove button
[33m3477594[m buyer base
[33m345992e[m Add scraper page base
[33m87b7e5d[m Wrap everything except analysis into a main-content for tab switching purposes later on
[33m6a54c4d[m make table scrollable
[33m001a4b6[m fix error with add category
[33m9d01be7[m repricer view order by competitor
[33mec03b6b[m repricer page that shows competitor listing history
[33m716c328[m Add one more rounding bracket to buying range
[33m22c0ac0[m buying analyser more data driven
[33m1d97909[m remove let me briefly explain how we price items in opening response for too high situation
[33m162d505[m Progress on buying module
[33mcb81666[m Progress on buying module
[33mf939170[m buying script
[33m9a22209[m refactor extracting checked competitor data
[33m837f23d[m buying reasoning text
[33maebe645[m buying range calculation
[33m98b42fd[m progress on buying module
[33m27b4f14[m cleanup scrapePrices() and also remove old buying analysis logic
[33m391f733[m start working on buying analysis module that extends from individual_item_analyser
[33m349d11d[m filtering by scraping works
[33m518f01c[m send attribute data along to the scraper
[33m139b939[m sort models alphabetically to find them easier
[33mbf027cf[m display item name from nospos in analyse page on top
[33m3bb