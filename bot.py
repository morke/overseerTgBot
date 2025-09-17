import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    DEFAULT_IS_4K,
    OWNER_TELEGRAM_USER_ID,
    OVERSEERR_API_KEY,
    OVERSEERR_URL,
    TELEGRAM_BOT_TOKEN,
    TMDB_IMAGE_BASE,
    validate_config,
)
from overseerr_client import OverseerrClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_title_year_type(item: Dict[str, Any]) -> Tuple[str, Optional[str], str]:
    media_type = item.get("mediaType") or item.get("media_type") or "movie"
    title = item.get("title") or item.get("name") or "(untitled)"
    date = item.get("releaseDate") or item.get("firstAirDate") or item.get("release_date") or item.get("first_air_date")
    year = date[:4] if isinstance(date, str) and len(date) >= 4 else None
    return title, year, ("movie" if media_type == "movie" else "tv series")


def _is_available(item: Dict[str, Any]) -> bool:
    media_info = item.get("mediaInfo") or {}
    status = media_info.get("status")
    if isinstance(status, str):
        return status.upper() == "AVAILABLE"
    if isinstance(status, int):
        return status >= 4  # heuristic to treat as available
    return False


def _build_caption(item: Dict[str, Any]) -> str:
    title, year, type_label = _extract_title_year_type(item)
    available = _is_available(item)
    status_text = "in library" if available else "not in library"
    status_icon = "✅" if available else "❌"
    lines: List[str] = []
    lines.append(f"<b>{title}</b> - ({type_label})")
    if year:
        lines.append(f"Year - {year}")
    lines.append("")
    lines.append(f"{status_icon} Status: {status_text}")
    return "\n".join(lines)


def _extract_imdb_and_rt(details: Dict[str, Any]) -> Dict[str, Optional[str]]:
    ext = details.get("externalIds") or details.get("external_ids") or {}
    imdb_id = ext.get("imdbId") or ext.get("imdb_id")

    ratings = details.get("ratings") or {}
    imdb_rating = None
    rt_tomato = None
    rt_popcorn = None
    rt_url = None

    if isinstance(ratings, dict):
        # Common shapes
        imdb_block = ratings.get("imdb") or ratings.get("IMDb") or ratings.get("imdbRating")
        if isinstance(imdb_block, dict):
            imdb_rating = (
                str(imdb_block.get("value"))
                or str(imdb_block.get("rating"))
                or str(imdb_block.get("score"))
            )
            # Some combined endpoints may include a direct URL
            if not imdb_id:
                maybe_url = imdb_block.get("url")
                if isinstance(maybe_url, str) and maybe_url.startswith("http"):
                    # Derive imdb_id from URL if possible
                    try:
                        imdb_id = maybe_url.rstrip("/").split("/")[-1]
                    except Exception:
                        pass
        elif isinstance(imdb_block, (int, float, str)):
            imdb_rating = str(imdb_block)

        # Rotten Tomatoes combined shapes
        rt_block = ratings.get("rottenTomatoes") or ratings.get("rotten_tomatoes") or ratings.get("rotten")
        if isinstance(rt_block, dict):
            # Nested critics/audience blocks or flat fields
            critics = rt_block.get("critics") if isinstance(rt_block.get("critics"), dict) else None
            audience = rt_block.get("audience") if isinstance(rt_block.get("audience"), dict) else None
            if critics:
                rt_tomato = str(critics.get("score") or critics.get("rating") or critics.get("value"))
                if not rt_url:
                    rt_url = critics.get("url")
            if audience:
                rt_popcorn = str(audience.get("score") or audience.get("rating") or audience.get("value"))
                if not rt_url:
                    rt_url = audience.get("url")
            # Flat fallbacks
            if not rt_tomato:
                rt_tomato = (
                    str(rt_block.get("tomatometer"))
                    or str(rt_block.get("tomatoMeter"))
                    or str(rt_block.get("criticsScore"))
                )
            if not rt_popcorn:
                rt_popcorn = (
                    str(rt_block.get("audienceScore"))
                    or str(rt_block.get("popcornMeter"))
                )
            if not rt_url:
                rt_url = rt_block.get("url")

        # Overseerr /{movie|tv}/{id}/ratings returns a FLAT RT object
        if not (rt_tomato or rt_popcorn):
            if any(k in ratings for k in ("criticsScore", "audienceScore")):
                if ratings.get("criticsScore") is not None:
                    rt_tomato = str(ratings.get("criticsScore"))
                if ratings.get("audienceScore") is not None:
                    rt_popcorn = str(ratings.get("audienceScore"))
                if not rt_url and isinstance(ratings.get("url"), str):
                    rt_url = ratings.get("url")

    imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else None

    return {
        "imdb_id": imdb_id,
        "imdb_rating": imdb_rating,
        "imdb_url": imdb_url,
        "rt_tomato": rt_tomato,
        "rt_popcorn": rt_popcorn,
        "rt_url": rt_url,
    }


def _extract_trailer_url(details: Dict[str, Any]) -> Optional[str]:
    # Prefer explicit relatedVideos.url when provided by Overseerr details endpoint
    related = details.get("relatedVideos")
    if isinstance(related, list):
        for preferred_type in ("Trailer", "Teaser"):
            for v in related:
                url = v.get("url")
                if v.get("site") == "YouTube" and v.get("type") == preferred_type and isinstance(url, str):
                    return url
        for v in related:
            url = v.get("url")
            if v.get("site") == "YouTube" and isinstance(url, str):
                return url
    # Fallback: TMDb videos structure if present
    videos = details.get("videos") or {}
    results = videos.get("results") if isinstance(videos, dict) else None
    if isinstance(results, list):
        for preferred_type in ("Trailer", "Teaser"):
            for v in results:
                if v.get("site") == "YouTube" and v.get("type") == preferred_type and v.get("key"):
                    return f"https://youtu.be/{v.get('key')}"
        for v in results:
            if v.get("site") == "YouTube" and v.get("key"):
                return f"https://youtu.be/{v.get('key')}"
    return None


def _append_enrichment_to_caption(base_caption: str, details: Dict[str, Any]) -> str:
    parts: List[str] = [base_caption]
    rates = _extract_imdb_and_rt(details)
    parts.append("")

    # IMDb line (as link, optionally with rating)
    if rates.get("imdb_url"):
        label = "IMDb" if not (rates.get("imdb_rating") and rates["imdb_rating"] not in ("None", "nan")) else f"IMDb: {rates['imdb_rating']}"
        parts.append(f"<a href=\"{rates['imdb_url']}\">{label}</a>")

    # Rotten Tomatoes lines with icons, link if URL is known
    rt_url = rates.get("rt_url") or "https://www.rottentomatoes.com/"
    if rates.get("rt_tomato") and rates["rt_tomato"] not in ("None", "nan"):
        tomato_line = f"🍅 Tomatometer : {rates['rt_tomato']}%"
        parts.append(f"<a href=\"{rt_url}\">{tomato_line}</a>")
    if rates.get("rt_popcorn") and rates["rt_popcorn"] not in ("None", "nan"):
        popcorn_line = f"🍿 Popcorn: {rates['rt_popcorn']}%"
        parts.append(f"<a href=\"{rt_url}\">{popcorn_line}</a>")

    trailer = _extract_trailer_url(details)
    if trailer:
        parts.append("")
        parts.append(f"<a href=\"{trailer}\">🎬 Trailer</a>")

    return "\n".join(parts)


def _build_keyboard(item: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    media_type = item.get("mediaType") or item.get("media_type") or "movie"
    media_id = item.get("id")
    if media_id is None:
        return None
    buttons: List[InlineKeyboardButton] = []
    # Show Download only if not yet available
    if not _is_available(item):
        buttons.append(InlineKeyboardButton("⏬ Download", callback_data=f"req|{media_type}|{media_id}"))
    # Show Recommendations for TV and Movie items
    if media_type in ("tv", "movie"):
        buttons.append(InlineKeyboardButton("👀 Recommendations", callback_data=f"rec|{media_type}|{media_id}"))
    if not buttons:
        return None
    return InlineKeyboardMarkup([buttons])


def _is_owner(update: Update) -> bool:
    if not OWNER_TELEGRAM_USER_ID:
        return True
    try:
        owner_id = int(OWNER_TELEGRAM_USER_ID)
    except Exception:
        return False
    user_id = update.effective_user.id if update.effective_user else None
    return user_id == owner_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_message
    if not _is_owner(update):
        await update.effective_message.reply_text("This bot is restricted to the owner.")
        return
    await update.effective_message.reply_text("Send a movie or TV title.")


async def on_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_message
    if not _is_owner(update):
        return
    query = (update.effective_message.text or "").strip()
    if not query:
        await update.effective_message.reply_text("Empty query. Please enter a title.")
        return

    client: OverseerrClient = context.application.bot_data.get("overseerr_client")
    try:
        data = await client.search(query)
    except Exception as e:  # noqa: BLE001
        logger.exception("Search failed")
        await update.effective_message.reply_text(f"Overseerr search error: {e}")
        return

    results: List[Dict[str, Any]] = list(data.get("results") or [])
    if not results:
        await update.effective_message.reply_text("No results found.")
        return

    # Filter only movie/tv and limit
    filtered = [r for r in results if (r.get("mediaType") or r.get("media_type")) in ("movie", "tv")]
    if not filtered:
        filtered = results
    for item in filtered[:10]:
        poster_path = item.get("posterPath") or item.get("poster_path")
        base_caption = _build_caption(item)
        # Try to enrich caption with ratings, trailer and overview
        media_type = item.get("mediaType") or item.get("media_type") or "movie"
        details: Dict[str, Any] = {}
        try:
            if item.get("id") is not None:
                details = await client.get_details(media_type, int(item["id"]))
                # Fetch ratings from Overseerr ratings endpoint and merge if available
                try:
                    ratings = await client.get_ratings(media_type, int(item["id"]))
                    if isinstance(ratings, dict) and ratings:
                        # Merge into details under 'ratings'
                        existing = details.get("ratings") if isinstance(details, dict) else None
                        if isinstance(existing, dict):
                            existing.update(ratings)
                        else:
                            details["ratings"] = ratings
                except Exception:
                    pass
        except Exception:
            details = {}
        caption = _append_enrichment_to_caption(base_caption, details) if details else base_caption
        keyboard = _build_keyboard(item)
        try:
            if poster_path:
                url = f"{TMDB_IMAGE_BASE}{poster_path}"
                await update.effective_message.reply_photo(photo=url, caption=caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            else:
                await update.effective_message.reply_text(caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except Exception:  # noqa: BLE001
            # Fallback to text if photo fails
            await update.effective_message.reply_text(caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.callback_query
    if not _is_owner(update):
        await update.callback_query.answer()
        return
    query = update.callback_query
    await query.answer()
    data = (query.data or "")
    if data.startswith("req|"):
        _, media_type, media_id_str = data.split("|", 2)
    elif data.startswith("rec|"):
        _, media_type, media_id_str = data.split("|", 2)
        try:
            rec_id = int(media_id_str)
        except ValueError:
            await query.message.reply_text("Invalid identifier.")
            return

        client: OverseerrClient = context.application.bot_data.get("overseerr_client")
        try:
            if media_type == "tv":
                rec = await client.get_tv_recommendations(rec_id)
            else:
                rec = await client.get_movie_recommendations(rec_id)
            rec_results: List[Dict[str, Any]] = list(rec.get("results") or [])
            if not rec_results:
                await query.message.reply_text("No recommendations found.")
                return

            # Show up to 10 recommendations
            for rec_item in rec_results[:10]:
                poster_path = rec_item.get("posterPath") or rec_item.get("poster_path")
                base_caption = _build_caption(rec_item)
                details: Dict[str, Any] = {}
                try:
                    if rec_item.get("id") is not None:
                        details = await client.get_details(media_type, int(rec_item["id"]))
                        try:
                            ratings = await client.get_ratings(media_type, int(rec_item["id"]))
                            if isinstance(ratings, dict) and ratings:
                                existing = details.get("ratings") if isinstance(details, dict) else None
                                if isinstance(existing, dict):
                                    existing.update(ratings)
                                else:
                                    details["ratings"] = ratings
                        except Exception:
                            pass
                except Exception:
                    details = {}
                caption = _append_enrichment_to_caption(base_caption, details) if details else base_caption
                kb = _build_keyboard({**rec_item, "mediaType": media_type})
                try:
                    if poster_path:
                        url = f"{TMDB_IMAGE_BASE}{poster_path}"
                        await query.message.reply_photo(photo=url, caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
                    else:
                        await query.message.reply_text(caption, reply_markup=kb, parse_mode=ParseMode.HTML)
                except Exception:
                    await query.message.reply_text(caption, reply_markup=kb, parse_mode=ParseMode.HTML)
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("Recommendations failed")
            await query.message.reply_text(f"Recommendations error: {e}")
            return
    else:
        return
    try:
        media_id = int(media_id_str)
    except ValueError:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Invalid identifier.")
        return

    client: OverseerrClient = context.application.bot_data.get("overseerr_client")

    try:
        created = await client.create_request(media_id=media_id, media_type=media_type, seasons=None, is_4k=DEFAULT_IS_4K)
        request_id = (
            (created.get("id") if isinstance(created, dict) else None)
            or (created.get("request", {}).get("id") if isinstance(created, dict) else None)
        )
        if request_id is not None:
            try:
                await client.approve_request(request_id=request_id, is_4k=DEFAULT_IS_4K)
            except Exception:
                logger.exception("Approve failed")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Request submitted and approved ✅")
    except Exception as e:  # noqa: BLE001
        logger.exception("Request failed")
        await query.message.reply_text(f"Request error: {e}")


async def _on_shutdown(app: Application) -> None:
    client: OverseerrClient = app.bot_data.get("overseerr_client")
    if client:
        await client.close()


def main() -> None:
    validate_config()
    app: Application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .rate_limiter(AIORateLimiter())
        .post_shutdown(_on_shutdown)
        .build()
    )

    client = OverseerrClient(base_url=OVERSEERR_URL, api_key=OVERSEERR_API_KEY)
    app.bot_data["overseerr_client"] = client

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_query))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()

