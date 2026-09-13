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

## გასწორება — ავტომატური ინსტალაცია

cPanel → **Terminal** (ან SSH), გადადი ბოტის საქაღალდეში და გაუშვი:

```bash
cd ~/vinpro-bot          # შენი ბოტის საქაღალდე
source /home/USER/virtualenv/vinpro-bot/3.11/bin/activate   # Setup Python App გაჩვენებს ზუსტ ბრძანებას
curl -fsSL -o install_cpanel.sh \
  "https://raw.githubusercontent.com/Kokrine/Kok-Car/claude/report-throwing-issue-smbnnn/deploy/install_cpanel.sh"
bash install_cpanel.sh
```

სკრიპტი თავად: ჩამოტვირთავს `vinpro/` მოდულს, დააინსტალირებს Playwright-სა და
Chromium-ს (თუ ჰოსტინგი ბლოკავს — მოძებნის სისტემურ Chromium-ს), გაუშვებს smoke
ტესტს და შექმნის `.env.vinpro`-ს სწორი პარამეტრებით. ხელახლა გაშვება უსაფრთხოა.

## გასწორება — ხელით (თუ Terminal არ გაქვს)

1. **ატვირთე `vinpro/` საქაღალდე** ბოტის root-ში (File Manager → Upload).

2. **დააინსტალირე დამოკიდებულებები** ("Setup Python App" → Run pip install):
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
   | `VINPRO_CHROMIUM_PATH` | ცარიელი | სისტემური Chromium-ის გზა, თუ `playwright install` დაბლოკილია |

5. **გაუშვი ბოტი მუდმივ პროცესად, არა Passenger-ის ქვეშ.**
   ეს ყველაზე მნიშვნელოვანი ნაბიჯია cPanel-ზე. Passenger idle worker-ს კლავს
   და ზუსტად ამ შეცდომას იწვევს. სამაგიეროდ:

   * cPanel → **Cron Jobs** → ყოველ 5 წუთში keepalive:
     ```
     */5 * * * * cd /home/USER/vinpro-bot && /home/USER/virtualenv/vinpro-bot/3.11/bin/python -c "import os,sys; sys.exit(0)" && pgrep -f "python bot.py" > /dev/null || nohup /home/USER/virtualenv/vinpro-bot/3.11/bin/python bot.py >> bot.log 2>&1 &
     ```
   * ან, თუ ჰოსტინგი უშვებს, **supervisord** / `screen` / `tmux`.

## შემოწმება

მოდული გატესტილია ორივე რეჟიმში (საერთო ბრაუზერი და ახალი ბრაუზერი ყოველ
მოთხოვნაზე) — ტესტი რეპოშია:

```bash
PYTHONPATH=. python tests/test_browser_manager.py
```

ის სპეციალურად კლავს ბრაუზერს რენდერის შუაში, იმავე
`Locator.count: Target page, context or browser has been closed` შეცდომას იღებს
და ამოწმებს, რომ მოთხოვნა მაინც წარმატებით სრულდება.

გასწორების შემდეგ სცადეთ ორი VIN **ერთდროულად**, ორი სხვადასხვა ანგარიშიდან —
სწორედ ეს სცენარი ტეხდა ბოტს. ორივეს უნდა მოუვიდეს PDF (თანმიმდევრულად, თუ
`VINPRO_MAX_CONCURRENT_RENDERS=1`).

თუ შეცდომა მაინც მეორდება, `bot.log`-ში ჩანს რეალური მიზეზი — გამოგზავნე
ლოგის ბოლო 50 ხაზი.

## დამატებით: კრედიტის ჩამოჭრა

`telegram_example.py`-ში კრედიტი ჩამოიჭრება **მხოლოდ მას შემდეგ**, რაც PDF
რეალურად შეიქმნა. თუ ბოტში ეს პირიქითაა, გადაიტანე ჩამოჭრა `reply_document`-ის
წინ, რომ შეცდომისას მომხმარებელს ბალანსი არ დაეკლოს.


---

# თუ Chromium არ ეშვება (SIGTRAP / SIGSEGV / smoke test failed)

cPanel/CloudLinux-ზე Chromium ხშირად მაშინვე კვდება. სიმპტომი ერთია, მიზეზი —
ოთხიდან ერთი. დიაგნოსტიკა:

```bash
cd ~/<ბოტის საქაღალდე>
bash deploy/probe_chromium.sh
```

სკრიპტი აჩვენებს ანგარიშის ლიმიტებს, `ldd`-ით შეამოწმებს დაკარგულ
ბიბლიოთეკებს და მიყოლებით გამოცდის Chromium-ის გაშვების 4 კონფიგურაციას.
ბოლოს დაბეჭდავს **ზუსტად იმ ხაზებს**, რაც `.env.vinpro`-ში უნდა ჩასვა.

| მიზეზი | როგორ ჩანს | გამოსავალი |
|---|---|---|
| აკლია სისტემური ბიბლიოთეკები | `ldd`-ში "not found" | ჰოსტინგს სთხოვე დაინსტალირება (შენ არ შეგიძლია shared-ზე) |
| CloudLinux LVE პროცესების ლიმიტი | SIGTRAP მაშინვე გაშვებაზე | `VINPRO_SINGLE_PROCESS=1` |
| მეხსიერების ლიმიტი | SIGKILL / OOM | `VINPRO_LOW_MEMORY=1` + `VINPRO_FRESH_BROWSER_PER_REQUEST=1` |
| `/dev/shm` პატარაა | კრახი გვერდის ჩატვირთვისას | `--disable-dev-shm-usage` (უკვე ჩართულია) |

## მნიშვნელოვანი: `VINPRO_SINGLE_PROCESS=1`-ის შეზღუდვა

`--single-process` რეჟიმში Chromium მხოლოდ **ერთ context-ს** უძლებს — მეორის
გახსნა კლავს ბრაუზერს იმავე შეცდომით (`BrowserContext.new_page: Target page,
context or browser has been closed`). ამიტომ `browser_manager.py` ავტომატურად
აიძულებს:

```
VINPRO_FRESH_BROWSER_PER_REQUEST=1
VINPRO_MAX_CONCURRENT_RENDERS=1
```

ესე იგი რეპორტები რიგრიგობით დამუშავდება — ნელია, მაგრამ მუშაობს. ეს ქცევა
გატესტილია `tests/test_browser_manager.py`-ით.

## თუ არაფერი შველის

Chromium shared hosting-ისთვის არ არის განკუთვნილი. თუ probe-მაც ვერ იპოვა
სამუშაო კონფიგურაცია, ან ჰოსტინგმა ბიბლიოთეკების დაინსტალირებაზე უარი თქვა —
ბოტი VPS-ზე უნდა გადავიდეს (ყველაზე იაფი $5/თვე საკმარისია). იქ ეს პრობლემა
საერთოდ არ არსებობს.
