import os
import random
import sys
import time
from datetime import date

import pandas as pd
import requests

# PARAMS - set according to preference
CAR_MAKE = os.environ.get('CAR_MAKE', 'Honda')  # brand
CAR_MODEL = os.environ.get('CAR_MODEL', 'Civic')  # specific model
ZIP = os.environ.get('ZIP', '10001')  # input as string

# FOLLOW README TO GET YOUR OWN AUTHORIZATION TOKEN.
# Keep it out of the source file - export it before running:
#     export CARFAX_AUTH='<your authorization token>'
AUTH = os.environ.get('CARFAX_AUTH', '').strip()

# Optional: a browser cookie header copied from the same request.
#     export CARFAX_COOKIE='uuid=...; api_token=...'
COOKIE = os.environ.get('CARFAX_COOKIE', '').strip()

BASE_URL = (
    'https://www.carfax.com/api/v2/consumers/auth0%7Coasc%7C454836195/findVehicles'
    '?tpQualityThreshold=150&tpPositions=1%2C2%2C3&tpValueBadges=GOOD%2CGREAT'
    '&zip={zip_code}&radius=50&sort=BEST&dynamicRadius=false'
    '&make={car_make}&model={car_model}&certified=false'
    '&oneAccountId=auth0%7Coasc%7C454836195'
)

USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36'
)

REQUEST_TIMEOUT = 30  # seconds - without this a hung request blocks forever


def build_headers():
    headers = {
        'authority': 'www.carfax.com',
        'sec-ch-ua': '"Google Chrome";v="93", " Not;A Brand";v="99", "Chromium";v="93"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'authorization': AUTH,
        'accept': 'application/json',
        'user-agent': USER_AGENT,
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'referer': 'https://www.carfax.com/',
        'accept-language': 'en-US,en;q=0.9',
    }
    if COOKIE:
        headers['cookie'] = COOKIE
    return headers


def fetch_page(session, url):
    """GET a search page and return its parsed JSON, or None if unusable."""
    response = session.get(url, headers=build_headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        print(f'Request failed with HTTP {response.status_code}: {url}')
        return None
    try:
        return response.json()
    except ValueError:
        # Carfax answers with an HTML block page when the token expired or the
        # IP got throttled - report that instead of crashing on a JSON error.
        print('Response was not JSON (expired token or blocked request?)')
        return None


def request_carfax(zip_code, car_make, car_model):
    if not AUTH:
        sys.exit('CARFAX_AUTH is not set - see README for how to obtain it.')

    scraped_results = []
    todays_date = date.today().strftime('%m-%d-%Y')  # date for exporting

    with requests.Session() as session:
        # initial request to find # pages for current search
        first_page = fetch_page(
            session,
            BASE_URL.format(zip_code=zip_code, car_make=car_make, car_model=car_model),
        )
        if first_page is None:
            sys.exit('Could not read the first page of results.')

        pages_in_search = first_page.get('totalPageCount', 0)  # number of pages
        print(
            f'There are {pages_in_search} pages of search results',
            f'for {car_make} {car_model} in Area Code: {zip_code}',
        )

        for x in range(pages_in_search):  # scraping each page of search results
            print('Scraping page', x, '...')
            url = BASE_URL.format(
                zip_code=zip_code, car_make=car_make, car_model=car_model
            ) + f'&page={x}'
            json_res = fetch_page(session, url)
            if json_res is None:
                continue

            for cars in json_res.get('listings', []):
                dealer = cars.get('dealer') or {}
                listing_details = {
                    'year': cars.get('year'),
                    'make': cars.get('make'),
                    'model': cars.get('model'),
                    'list_price': cars.get('listPrice'),
                    'mileage': cars.get('mileage'),
                    'dealer_address': dealer.get('address'),
                    'dealer_city': dealer.get('city'),
                    'dealer_state': dealer.get('state'),
                    'dealer_name': dealer.get('name'),
                    'link': cars.get('vdpUrl'),
                }
                # add listing details as dict to ongoing list
                scraped_results.append(listing_details)

            # adding delay to prevent IP ban -> increase delay for larger scrapes
            time.sleep(random.uniform(0, 0.8))

    if not scraped_results:
        print('No listings found - nothing to export.')
        return

    scraped_results = pd.DataFrame(scraped_results)  # convert list of dicts to df
    scraped_results = scraped_results.drop_duplicates(subset=['link'])  # dedupe

    print(
        'Successfully scraped',
        str(len(scraped_results)),
        car_make,
        car_model,
        'listing(s) from Area Code:',
        zip_code,
    )
    os.makedirs('scrapes', exist_ok=True)
    scraped_results.to_excel(
        'scrapes/{}_{}_{}_scrapes_{}.xlsx'.format(
            car_make, car_model, zip_code, todays_date
        )
    )


if __name__ == '__main__':
    request_carfax(ZIP, CAR_MAKE, CAR_MODEL)
