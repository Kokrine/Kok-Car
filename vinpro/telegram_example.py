"""Reference wiring for the Telegram VIN-report handler.

This is the shape the handler should have after the fix. Replace the body of
``build_report`` with the real Carfax/VIN scraping steps - everything around
it (browser lifecycle, queueing, retry, credit handling) is what stops the
"Target page, context or browser has been closed" errors.

Run with python-telegram-bot >= 20 (async).
"""

from __future__ import annotations

import logging
import os

from playwright.async_api import Page
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from vinpro.browser_manager import is_closed_error, manager, render_with_retry

log = logging.getLogger(__name__)

REPORT_URL = os.environ.get("VINPRO_REPORT_URL", "https://example.com/vin/{vin}")


async def build_report(page: Page, vin: str) -> bytes:
    """Render the VIN report and return it as PDF bytes.

    Every wait here has an explicit timeout so a slow page fails as a timeout
    (retryable, reportable) instead of hanging until the worker is recycled.
    """
    await page.goto(REPORT_URL.format(vin=vin), wait_until="domcontentloaded")

    report = page.locator("#report")
    await report.wait_for(state="visible", timeout=60_000)

    if await page.locator("text=No record found").count():
        raise LookupError(vin)

    return await page.pdf(format="A4", print_background=True)


async def handle_vin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    vin = (update.message.text or "").strip().upper()
    if len(vin) != 17:
        await update.message.reply_text("VIN უნდა იყოს 17 სიმბოლო.")
        return

    await update.message.reply_text(
        f"მოთხოვნა გაიგზავნა VIN-ისთვის: {vin}\n"
        "გთხოვთ დაელოდოთ, PDF რეპორტს მალე გამოგიგზავნით..."
    )

    try:
        pdf_bytes = await render_with_retry(build_report, vin)
    except LookupError:
        await update.message.reply_text(
            "ამ VIN-ზე ჩანაწერი ვერ მოიძებნა.\n\n"
            "კრედიტი არ დაგჭირვებიათ - ბალანსი უცვლელია."
        )
        return
    except Exception as exc:  # noqa: BLE001 - user gets a message either way
        # Log the real cause; the user sees a message they can act on.
        log.exception("report failed for %s", vin)
        if is_closed_error(exc):
            text = (
                "დროებითი ტექნიკური შეფერხება, სცადეთ ხელახლა 1-2 წუთში."
            )
        else:
            text = "ვერ მოხერხდა რეპორტის მიღება, სცადეთ ხელახლა."
        await update.message.reply_text(
            f"{text}\n\nკრედიტი არ დაგჭირვებიათ - ბალანსი უცვლელია."
        )
        return

    # Charge the credit only after the PDF actually exists.
    await update.message.reply_document(pdf_bytes, filename=f"{vin}.pdf")


async def _shutdown(_: Application) -> None:
    await manager.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = (
        Application.builder()
        .token(token)
        .post_shutdown(_shutdown)  # close Chromium exactly once, on exit
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vin))
    app.run_polling()


if __name__ == "__main__":
    main()
