# "Target page, context or browser has been closed" — მიზეზი და გასწორება

## რას ნიშნავს შეცდომა

```
ვერ მოხერხდა რეპორტის მიღება: Locator.count: Target page, context or browser has been closed
ვერ მოხერხდა რეპორტის მიღება: Locator.wait_for: Target page, context or browser has been closed
```

ეს **არ** ნიშნავს, რომ VIN არასწორია ან საიტმა დაგვბლოკა. ეს ნიშნავს, რომ სანამ
კოდი ელემენტს ელოდებოდა, **ბრაუზერი/context უკვე დახურული იყო**. შეცდომა
სხვადასხვა ადგილას ამოვარდა (`count` ერთხელ, `wait_for` მეორედ) — ეს ნიშანია,
რომ პრობლემა კონკრეტულ selector-ში კი არა, ბრაუზერის სიცოცხლის ციკლშია.

## რატომ ერთს უგდებს და მეორეს არა

| მიზეზი | რატომ ხდება შერჩევითად |
|---|---|
| **ერთი გლობალური ბრაუზერი ყველა მომხმარებლისთვის** | ვინც პირველი დაასრულებს, მისი `finally: await browser.close()` ხურავს იმავე ბრაუზერს, რომელსაც მეორე ჯერ იყენებს |
| **Chromium კვდება მეხსიერებით (OOM)** | cPanel-ზე მკაცრი RAM ლიმიტია; ორი რეპორტი ერთდროულად კლავს პროცესს |
| **Passenger / LiteSpeed worker-ის გადატვირთვა** | cPanel "Setup Python App" idle worker-ს კლავს — მასთან ერთად კვდება child Chromium-იც, სწორედ რენდერის შუაში |
| **Carfax სესია ერთია** | მეორე login პირველს აგდებს |

## გასწორება — რა ატვირთო cPanel-ში

ამ რეპოში დამატებულია მზა მოდული: **`vinpro/browser_manager.py`**.

1. **ატვირთე `vinpro/` საქაღალდე** ბოტის root-ში (File Manager → Upload, ან
   `git pull` თუ სერვერზე git გაქვს).

2. **დააინსტალირე დამოკიდებულებები** (Terminal ან "Setup Python App" → Run
   pip install):
   ```
   pip install -r vinpro/requirements.txt
   python -m playwright install chromium
   ```

3. **ჩაასწორე handler-ი.** ნახე `vinpro/telegram_example.py` — იქ სრული
   ნიმუშია. მოკლედ: წაშალე ბოტიდან ყველა `browser = await p.chromium.launch()`
   და `await browser.close()` handler-ის შიგნით, და ჩაანაცვლე:

   ```python
   from vinpro.browser_manager import render_with_retry, manager

   async def build_report(page, vin):
       await page.goto(f"https://.../{vin}", wait_until="domcontentloaded")
       await page.locator("#report").wait_for(state="visible", timeout=60_000)
       return await page.pdf(format="A4")

   pdf_bytes = await render_with_retry(build_report, vin)
   ```

   `render_with_retry` თავად ზრუნავს იმაზე, რომ:
   * ყოველ მოთხოვნას **თავისი `BrowserContext`** ჰქონდეს (არასდროს საერთო page);
   * ერთდროულად მხოლოდ N რეპორტი მუშავდებოდეს (semaphore — default 1);
   * მკვდარი ბრაუზერი **ავტომატურად თავიდან გაეშვას** და მოთხოვნა 1-ჯერ
     გამეორდეს;
   * ბრაუზერი დაიხუროს **მხოლოდ ბოტის გამორთვისას** (`manager.shutdown()`).

4. **გარემოს ცვლადები** (Setup Python App → Environment variables):

   | ცვლადი | მნიშვნელობა | აღწერა |
   |---|---|---|
   | `VINPRO_MAX_CONCURRENT_RENDERS` | `1` | პარალელური რეპორტების ლიმიტი |
   | `VINPRO_FRESH_BROWSER_PER_REQUEST` | `1` | თუ RAM ცოტაა — ყოველ მოთხოვნაზე ახალი ბრაუზერი (ნელია, მაგრამ უტყუარი) |
   | `VINPRO_NAV_TIMEOUT_MS` | `60000` | ნავიგაციის timeout |
   | `VINPRO_HEADLESS` | `1` | headless რეჟიმი |

5. **გაუშვი ბოტი მუდმივ პროცესად, არა Passenger-ის ქვეშ.**
   ეს ყველაზე მნიშვნელოვანი ნაბიჯია cPanel-ზე. Passenger idle worker-ს კლავს
   და ზუსტად ამ შეცდომას იწვევს. სამაგიეროდ:

   * cPanel → **Cron Jobs** → ყოველ 5 წუთში keepalive:
     ```
     */5 * * * * cd /home/USER/vinpro-bot && /home/USER/virtualenv/vinpro-bot/3.11/bin/python -c "import os,sys; sys.exit(0)" && pgrep -f "python bot.py" > /dev/null || nohup /home/USER/virtualenv/vinpro-bot/3.11/bin/python bot.py >> bot.log 2>&1 &
     ```
   * ან, თუ ჰოსტინგი უშვებს, **supervisord** / `screen` / `tmux`.

## შემოწმება

გასწორების შემდეგ სცადეთ ორი VIN **ერთდროულად**, ორი სხვადასხვა ანგარიშიდან —
სწორედ ეს სცენარი ტეხდა ბოტს. ორივეს უნდა მოუვიდეს PDF (თანმიმდევრულად, თუ
`VINPRO_MAX_CONCURRENT_RENDERS=1`).

თუ შეცდომა მაინც მეორდება, `bot.log`-ში ჩანს რეალური მიზეზი — გამოგზავნე
ლოგის ბოლო 50 ხაზი.

## დამატებით: კრედიტის ჩამოჭრა

`telegram_example.py`-ში კრედიტი ჩამოიჭრება **მხოლოდ მას შემდეგ**, რაც PDF
რეალურად შეიქმნა. თუ ბოტში ეს პირიქითაა, გადაიტანე ჩამოჭრა `reply_document`-ის
წინ, რომ შეცდომისას მომხმარებელს ბალანსი არ დაეკლოს.
