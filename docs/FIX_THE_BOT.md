# ზუსტი გასწორება — `telegram-carfax-bot-new`

ეს დოკუმენტი ეყრდნობა **ნამდვილ კოდს** (`collect_context.py`-ის შედეგი) და
**რეპროდუცირებულ ბაგს** (`tests/test_shared_close_bug.py`).

## მიზეზი — დადასტურებული, არა ვარაუდი

არქიტექტურა ასეთია:

* `bot.py` უშვებს **ერთ** Chromium-ს `--remote-debugging-port={CDP_PORT}`-ით
  და ინახავს `_browser`-ში;
* `carfax_web_api.py` უერთდება მას `connect_over_cdp()`-ით და ინახავს
  `_shared_browser`-ში (module-level, ანუ **საერთო ყველა მომხმარებლისთვის**);
* ყველა მომხმარებლის გვერდი ამ ერთი კავშირით იქმნება.

`carfax_web_api.py`, ხაზები 100-105:

```python
if _shared_browser is not None:
    try:
        await _shared_browser.close()     # <-- ხაზი 102
    except Exception:
        pass
    _shared_browser = None
```

**`close()` CDP კავშირზე ხურავს ყველა გვერდს, რომელიც ამ კავშირით შეიქმნა.**
როცა ერთი მომხმარებლის მოთხოვნა reconnect-ზე მიდის, მეორის რეპორტი, რომელიც
სწორედ ამ წამს ირენდერება, კვდება.

გატესტილია და აღწარმოებულია სიტყვასიტყვით:

```
PASS  bug reproduced - Locator.count: Target page, context or browser has been closed
PASS  bug reproduced - Locator.wait_for: Target page, context or browser has been closed
PASS  the browser survived, which is why the other user still got a PDF
```

ბოლო ხაზი ხსნის მთავარ თავსატეხს: **ბრაუზერი ცოცხალი რჩება**, ამიტომ მეორე
მომხმარებელს რეპორტი უწყვეტად მიდიოდა.

## გასწორება 1 — `carfax_web_api.py` (მთავარი, 4 ხაზი)

ხაზები 100-105, შეცვალე ასე:

```python
        if _shared_browser is not None:
            # არასდროს დახურო CDP კავშირი: მასზეა სხვისი გვერდებიც.
            # უბრალოდ ჩამოვიშოროთ მითითება და თავიდან დავუკავშირდეთ.
            _shared_browser = None
```

ანუ `await _shared_browser.close()` **წაიშალოს**. სხვა არაფერი.

## გასწორება 2 — `bot.py` keepalive (ხაზები 145-166, 199-204)

`_browser_keepalive()` ყოველ 30 წამში ამოწმებს კავშირს და ჩავარდნისას
**ცვლის გლობალურ `_browser`-ს**. თუ ამ დროს ვიღაცის რეპორტი ირენდერება,
იგივე შეცდომა მიიღება — უბრალოდ უფრო იშვიათად.

ხაზი 156-ის `await _browser.close()` მხოლოდ მაშინ უნდა შესრულდეს, როცა
არცერთი მოთხოვნა არ მუშაობს. უმარტივესი გზა — მრიცხველი:

```python
_inflight = 0            # რამდენი რეპორტი მუშავდება ახლა

# რეპორტის დასაწყისში:  _inflight += 1
# finally-ში:           _inflight -= 1

# keepalive-ში და relaunch-ის წინ:
if _inflight > 0:
    return               # არ შეეხო ბრაუზერს, სანამ ვინმე იყენებს
```

## გასწორება 3 — `vinpro` მოდულის ჩართვა

`browser_manager.py`-ს დაემატა **CDP რეჟიმი** სწორედ ამ არქიტექტურისთვის.
`.env.vinpro`-ში:

```
VINPRO_CDP_URL=http://127.0.0.1:<CDP_PORT>
```

ამ რეჟიმში მენეჯერი **არასდროს ხურავს ბრაუზერს** (ის შენი არაა), აძლევს
ყოველ მოთხოვნას თავის context-ს და აწესრიგებს რიგს. შემდეგ handler-ში:

```python
from vinpro.browser_manager import render_with_retry

async def build_report(page, vin):
    ...   # ის ნაბიჯები, რაც უკვე გაქვს
    return await page.pdf(format="A4")

pdf_bytes = await render_with_retry(build_report, vin)
```

გატესტილია ნამდვილ CDP-ზე: 4 პარალელური რენდერი, reconnect რენდერის შუაში,
და მფლობელის ბრაუზერი ხელუხლებელი — `tests/test_cdp_mode.py`,
`tests/test_shared_close_bug.py`.

## გასწორება 4 — `login_setup.py`

ეს ცალკე, ხელით გასაშვები სკრიპტია (`headless=False`, `input()` ელოდება
Enter-ს). **მას გასწორება არ სჭირდება** — ბოტს არ იყენებს. ანალიზატორმა
სამართლიანად მონიშნა, მაგრამ ამ კონტექსტში `browser.close()` სწორია: ის
თავის ბრაუზერს ხურავს.

ერთადერთი შენიშვნა: ხაზი 31, `page.goto(LOGIN_URL)` timeout-ის გარეშე.

## მეორე მიზეზი — ანგარიშის პროცესების ლიმიტი (დადასტურებული)

`probe_deep.py`-მ ბრაუზერის ნამდვილი stderr აიღო:

```
pthread_create: Resource temporarily unavailable (11)
Zygote could not fork: process_type gpu-process numfds 4 child_pid -1
```

ორივე `EAGAIN`-ია: **ანგარიშმა ვერ შექმნა ახალი პროცესი/thread.** CloudLinux-ზე
ეს LVE NPROC ლიმიტია, რომელსაც `ulimit -u` **არ აჩვენებს** — წერს `unlimited`-ს,
მაშინ როცა ლიმიტი სხვაგან იზომება.

გადამწყვეტი დეტალი probe-იდან: `chrome processes already running: 1`. ბოტის
Chromium უკვე მუშაობდა და ანგარიშის budget-ს იკავებდა. მეორე ბრაუზერს ადგილი
აღარ რჩებოდა.

**ეს პირდაპირ უკავშირდება მთავარ ბაგს.** როცა ორი მომხმარებელი ერთდროულად
ითხოვს რეპორტს, Chromium მეტ renderer პროცესს ქმნის — ლიმიტს აწყდება, ბავშვი
პროცესი ვერ იქმნება, ბრაუზერი კვდება, და დანარჩენი მოთხოვნები იღებენ
`Target page, context or browser has been closed`-ს. ანუ ორი დამოუკიდებელი
გზაა ერთი და იმავე შეცდომისკენ:

1. `_shared_browser.close()` — გასწორება 1 (ზემოთ);
2. პროცესების ლიმიტი — ქვემოთ.

### გაზომვა

```bash
python deploy/measure_limits.py
```

მხოლოდ `/proc`-ს კითხულობს, არაფერს ქმნის — უსაფრთხოა მომუშავე ბოტზე.
გამოიტანს რამდენი პროცესი/thread გიკავია და მზა ტექსტს ჰოსტინგისთვის.

### გამოსავალი

**ა) მეორე ბრაუზერი საერთოდ არ გაუშვა.** ეს ისედაც შენი არქიტექტურაა —
`.env.vinpro`-ში ჩაწერე:

```
VINPRO_CDP_URL=http://127.0.0.1:<CDP_PORT>
```

პორტს იპოვი: `grep -n "CDP_PORT" bot.py carfax_web_api.py | head`

**ბ) შეამცირე Chromium-ის მადა** — `.env.vinpro`:

```
VINPRO_MAX_CONCURRENT_RENDERS=1
VINPRO_LOW_MEMORY=1
```

**გ) სთხოვე ჰოსტინგს NPROC-ის გაზრდა.** `measure_limits.py` მზა ტექსტს
დაგიბეჭდავს ზუსტი ციფრებით.

### რაც *არ* არის პრობლემა

მასპინძლის რკინა ჯანმრთელია — 197 GB RAM, `/dev/shm` 95 GB, ბიბლიოთეკები
სრულად, ბინარი პირდაპირ მუშაობს (`Google Chrome for Testing 148.0.7778.96`).
**VPS არ გჭირდება** — საკმარისია ანგარიშის ლიმიტი და ერთი ბრაუზერი.
