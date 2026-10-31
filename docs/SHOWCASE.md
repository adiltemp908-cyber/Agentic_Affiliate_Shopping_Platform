# Search examples and screenshots

These are actual browser captures from the populated development app on **31 October 2026**, using local Qwen and hybrid retrieval. Each example pairs the search results with the retailer page opened by clicking **View on Amazon/Flipkart** on the first result. Product cards, replies and retailer pages were not mocked or rewritten for the images. Open an image to inspect the text at full resolution.

The capture checks verify both the saved requirements and returned product fields. This demonstrates the recorded behavior of these examples, not universal language understanding or independently tested product quality. Prices and availability can change. The interface uses clearly labeled illustrations/category placeholders rather than product photographs.

## 1. A round digital alarm clock

**Request:** “I want a digital alarm clock that is round in shape”

**Follow-up:** “Nothing else, just show me the options”

The search preserves `alarm clock`, `shape: round` and `display: digital`. The captured run returned five Amazon candidates. The confirmation continues the existing brief rather than turning “Nothing” into a brand restriction.

![Round digital alarm clock search with preserved shape and display requirements](screenshots/round-digital-alarm-clock.png)

**Top result after clicking through:** [Zollyss round digital alarm clock on Amazon](https://www.amazon.in/dp/B0GJSWLRJ4). The retailer page displays the actual product photograph, title and ₹699 price at capture time.

![Amazon product page opened from the first round digital alarm clock result](screenshots/round-digital-alarm-clock-product.png)

## 2. An OLED television

**Request:** “I want a oled TV”

The request becomes a television search with a recorded OLED display requirement. The captured run returned six Flipkart candidates. The extraction and matching fields agree, so OLED is checked as a specification rather than treated as an unsupported sentence. These remain retailer-recorded display claims, not independent panel verification.

![OLED television search showing the display requirement and matching catalog candidates](screenshots/oled-televisions.png)

**Top result after clicking through:** [LIMEBERRY 125 cm (50 inch) television on Flipkart](https://www.flipkart.com/limeberry-125-cm-50-inch-oled-ultra-hd-4k-smart-android-tv/p/itm1a9381dece63e?pid=TVSGMWP2WVG2CBSZ). The page shows the retailer's OLED description and ₹36,386 listed price. It also shows a delivery restriction with no delivery location selected; the shortlist does not guarantee local delivery.

![Flipkart product page opened from the first OLED television result](screenshots/oled-televisions-product.png)

## 3. A laptop within a budget and minimum specifications

**Request:** “I need a laptop under 60000 with at least 16 GB RAM and 512 GB SSD”

The shortlist applies a strict price ceiling below ₹60,000, at least 16 GB RAM and at least 512 GB storage. Four candidates were returned across Amazon and Flipkart. Known shipping is included in the budget check; unknown shipping remains disclosed rather than treated as a guaranteed delivered price.

![Laptop search with price, RAM and storage requirements and offers from both retailers](screenshots/laptop-budget-specifications.png)

**Top result after clicking through:** [HP Professional 15, 16 GB RAM / 512 GB SSD, on Amazon](https://www.amazon.in/dp/B0GHSN1N24). This is the same first-listed laptop shown in the search results above.

![Amazon product page opened from the first laptop result](screenshots/laptop-budget-specifications-product.png)

## Reproduce the captures

Follow [Setup](SETUP.md), populate and index a recent catalog, start the local app, and run:

```powershell
node scripts/capture_showcase.cjs
```

The script needs Playwright and installed Chrome. An optional example ID, such as `round-digital-alarm-clock`, captures just that scenario. It saves the search image, clicks the first result's retailer link and captures the opened product page. A future run can return different offers or fail if current inventory does not meet the requirements or a retailer page is unavailable. It will not fabricate products to recreate these images.

The development catalog and saved chats are not included in this repository. The application source, collection tools and documented import format are provided so a new catalog can be built separately.
