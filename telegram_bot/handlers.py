"""All Telegram handlers: main menu, login conversation, course navigation,
file selection, upload confirmation, queue control, history, search and
settings.  Every administrative handler is guarded by @admin_only."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app_api.provider import (
    AuthenticationError,
    NotAuthorizedError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    SessionExpiredError,
)
from config import CONFIG
from database.db import get_setting, set_setting
from services import (
    course_service,
    queue_service,
    search_service,
    statistics_service,
    upload_service,
)
from telegram_bot import keyboards as kb
from telegram_bot.formatter import current_template
from utils.helpers import file_type_icon, human_size, paginate, truncate
from utils.logger import get_logger, log_event
from utils.security import admin_only, is_admin
from utils.validators import (
    ValidationError,
    validate_caption_template,
    validate_chat_id,
    validate_int_range,
    validate_password,
    validate_search_query,
    validate_username,
)

logger = get_logger(__name__)

# Conversation states
LOGIN_USERNAME, LOGIN_PASSWORD = range(2)


# ============================================================ helpers
async def _edit_or_send(update: Update, text: str,
                        reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Edit the callback message when possible, otherwise send a new one."""
    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup)
            return
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        # fall through: message may be too old to edit
    if update.effective_chat:
        await update.effective_chat.send_message(text, reply_markup=reply_markup)


def _selection(context: ContextTypes.DEFAULT_TYPE) -> set[int]:
    return context.user_data.setdefault("sel", set())


async def _provider_error_text(exc: Exception) -> str:
    if isinstance(exc, ProviderNotConfiguredError):
        return str(exc)
    if isinstance(exc, AuthenticationError):
        return f"❌ Login failed: {exc}"
    if isinstance(exc, SessionExpiredError):
        return f"🔑 {exc}"
    if isinstance(exc, NotAuthorizedError):
        return f"🚫 {exc}"
    if isinstance(exc, ProviderUnavailableError):
        return f"🌐 Source API problem: {exc}\nPlease try again in a moment."
    if isinstance(exc, ProviderError):
        return f"⚠️ {exc}"
    return "⚠️ Unexpected error. Details were logged."


# ============================================================ /start & menu
@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main_menu(update, context)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Public helper so the owner can discover their ADMIN_USER_ID."""
    user = update.effective_user
    if user and update.effective_message:
        await update.effective_message.reply_text(
            f"Your Telegram user id: {user.id}")


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting", None)
    logged_in = course_service.is_logged_in(update.effective_user.id)
    mode = "🧪 TEST MODE — uploads are simulated\n\n" if CONFIG.test_mode else ""
    text = (
        f"{mode}🏠 MAIN MENU\n\n"
        "Course Management & Authorized Export System\n"
        f"Login status: {'✅ logged in' if logged_in else '❌ not logged in'}\n\n"
        "Choose an option:"
    )
    await _edit_or_send(update, text, kb.main_menu(logged_in))


@admin_only
async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]

    if action in ("home", "cancel"):
        if action == "cancel":
            context.user_data.pop("awaiting", None)
        await show_main_menu(update, context)
    elif action == "batches":
        await show_batches(update, context, page=0)
    elif action == "upload":
        await show_queue(update, context)
    elif action == "stats":
        await show_statistics(update, context)
    elif action == "settings":
        await show_settings(update, context)
    elif action == "search":
        context.user_data["awaiting"] = ("search", None)
        await _edit_or_send(
            update,
            "🔍 Search uploads\n\nSend a search term "
            "(index number, title, batch, subject, topic, lecture, file type "
            "or Telegram message id):",
            InlineKeyboardMarkup([kb.nav_row(None)]),
        )
    elif action == "logout":
        await course_service.logout(update.effective_user.id)
        await _edit_or_send(update, "🚪 Logged out. Session cleared.",
                            kb.main_menu(False))


# ============================================================ login flow
@admin_only
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    log_event("INFO", "login_attempt", f"admin={update.effective_user.id}")
    await _edit_or_send(
        update,
        "🔐 Login to the source application\n\n"
        "Authentication happens ONLY via the official/authorized API.\n"
        "Your password is used once for the login call and never stored.\n\n"
        "Send your Application ID / Username:\n(or /cancel to abort)",
    )
    return LOGIN_USERNAME


@admin_only
async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["login_user"] = validate_username(update.message.text)
    except ValidationError as exc:
        await update.message.reply_text(f"⚠️ {exc}\nTry again or /cancel.")
        return LOGIN_USERNAME
    await update.message.reply_text(
        "Now send your password:\n(the message will be deleted immediately)")
    return LOGIN_PASSWORD


@admin_only
async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    try:
        password = validate_password(message.text)
    except ValidationError as exc:
        await message.reply_text(f"⚠️ {exc}\nTry again or /cancel.")
        return LOGIN_PASSWORD
    # remove password from chat history immediately
    try:
        await message.delete()
    except TelegramError:
        pass

    username = context.user_data.pop("login_user", "")
    status = await message.chat.send_message("⏳ Authenticating via official API...")
    try:
        account = await course_service.login(update.effective_user.id, username, password)
    except Exception as exc:  # noqa: BLE001 - converted to user-safe text
        logger.warning("login failed: %s", type(exc).__name__)
        log_event("WARNING", "login_failed", type(exc).__name__)
        await status.edit_text(await _provider_error_text(exc))
        await message.chat.send_message("🏠 MAIN MENU", reply_markup=kb.main_menu(False))
        return ConversationHandler.END
    finally:
        del password

    await status.edit_text(f"✅ Login successful — account: {account}")
    await message.chat.send_message(
        "🏠 MAIN MENU\n\nYou can now open 📚 My Batches.",
        reply_markup=kb.main_menu(True))
    return ConversationHandler.END


@admin_only
async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("login_user", None)
    await update.message.reply_text("❌ Login cancelled.")
    await show_main_menu(update, context)
    return ConversationHandler.END


# ============================================================ navigation
async def show_batches(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       page: int) -> None:
    try:
        provider = course_service.get_provider(update.effective_user.id)
        infos = await provider.get_batches()
    except Exception as exc:
        await _edit_or_send(update, await _provider_error_text(exc),
                            kb.main_menu(course_service.is_logged_in(update.effective_user.id)))
        return
    rows = course_service.upsert_batches(infos)
    if not rows:
        await _edit_or_send(update, "📚 My Batches\n\nNo authorized batches found.",
                            kb.main_menu(True))
        return
    markup, page, total = kb.batches_kb(rows, page)
    lines = ["📚 MY BATCHES", ""]
    shown, page, _ = paginate(rows, page)
    for i, b in enumerate(shown):
        extra = []
        if b.validity:
            extra.append(b.validity)
        if b.subject_count is not None:
            extra.append(f"{b.subject_count} subjects")
        if b.lecture_count is not None:
            extra.append(f"{b.lecture_count} lectures")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"{i + 1}️⃣ {b.name}{suffix}")
    lines.append("")
    lines.append(f"Page {page + 1}/{total} — select a batch:")
    await _edit_or_send(update, "\n".join(lines), markup)


@admin_only
async def cb_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Router for all course-tree callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split(":")
    tag = parts[0]
    try:
        if tag == "nb":
            await show_batches(update, context, int(parts[1]))
        elif tag == "b":
            await show_subjects(update, context, int(parts[1]), 0)
        elif tag == "ns":
            await show_subjects(update, context, int(parts[1]), int(parts[2]))
        elif tag == "s":
            await show_topics(update, context, int(parts[1]), 0)
        elif tag == "nt":
            await show_topics(update, context, int(parts[1]), int(parts[2]))
        elif tag == "t":
            await show_lectures(update, context, int(parts[1]), 0)
        elif tag == "nl":
            await show_lectures(update, context, int(parts[1]), int(parts[2]))
        elif tag == "l":
            await show_files(update, context, int(parts[1]), 0)
        elif tag == "nf":
            await show_files(update, context, int(parts[1]), int(parts[2]))
    except Exception as exc:
        logger.exception("navigation error")
        await _edit_or_send(update, await _provider_error_text(exc),
                            InlineKeyboardMarkup([kb.nav_row(None)]))


async def show_subjects(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        batch_pk: int, page: int) -> None:
    batch = course_service.get_batch(batch_pk)
    if batch is None:
        await show_batches(update, context, 0)
        return
    provider = course_service.get_provider(update.effective_user.id)
    infos = await provider.get_subjects(batch.source_id)
    rows = course_service.upsert_subjects(batch_pk, infos)
    text = f"📚 {batch.name}\n\n📘 Subjects ({len(rows)}) — choose one:"
    await _edit_or_send(update, text, kb.subjects_kb(batch_pk, rows, page))


async def show_topics(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      subject_pk: int, page: int) -> None:
    subject = course_service.get_subject(subject_pk)
    if subject is None:
        await show_batches(update, context, 0)
        return
    batch = course_service.get_batch(subject.batch_id)
    provider = course_service.get_provider(update.effective_user.id)
    infos = await provider.get_topics(batch.source_id, subject.source_id)
    rows = course_service.upsert_topics(subject_pk, infos)
    text = (f"📚 {truncate(batch.name, 60)}\n📘 {subject.name}\n\n"
            f"📂 Topics / Chapters ({len(rows)}) — choose one:")
    await _edit_or_send(update, text, kb.topics_kb(subject.batch_id, subject_pk, rows, page))


async def show_lectures(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        topic_pk: int, page: int) -> None:
    topic = course_service.get_topic(topic_pk)
    if topic is None:
        await show_batches(update, context, 0)
        return
    subject = course_service.get_subject(topic.subject_id)
    batch = course_service.get_batch(subject.batch_id)
    provider = course_service.get_provider(update.effective_user.id)
    infos = await provider.get_lectures(batch.source_id, topic.source_id)
    rows = course_service.upsert_lectures(topic_pk, infos)
    text = (f"📘 {truncate(subject.name, 60)}\n📂 {topic.name}\n\n"
            f"🎓 Lectures ({len(rows)}) — choose one:")
    await _edit_or_send(update, text, kb.lectures_kb(topic.subject_id, topic_pk, rows, page))


async def show_files(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     lecture_pk: int, page: int) -> None:
    lecture = course_service.get_lecture(lecture_pk)
    if lecture is None:
        await show_batches(update, context, 0)
        return
    topic = course_service.get_topic(lecture.topic_id)
    provider = course_service.get_provider(update.effective_user.id)
    subject = course_service.get_subject(topic.subject_id)
    batch = course_service.get_batch(subject.batch_id)
    infos = await provider.get_files(batch.source_id, lecture.source_id)
    rows = course_service.upsert_files(lecture_pk, infos)
    selected = _selection(context)
    context.user_data["last_files_view"] = (lecture_pk, page)

    lines = [f"🎓 {lecture.name}", ""]
    for f in rows:
        size = human_size(f.file_size)
        lines.append(f"{file_type_icon(f.file_type)} {truncate(f.title, 50)}"
                     + (f"  [{size}]" if size else ""))
    lines.append("")
    lines.append(f"Selected so far: {len(selected)} file(s)")
    lines.append("Tap a file to select/deselect:")
    await _edit_or_send(update, "\n".join(lines),
                        kb.files_kb(lecture.topic_id, lecture_pk, rows, selected, page))


# ============================================================ selection
@admin_only
async def cb_file_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    parts = data.split(":")
    tag = parts[0]
    pk = int(parts[1])
    selected = _selection(context)

    if tag == "f":
        if pk in selected:
            selected.discard(pk)
            await query.answer("Removed from selection")
        else:
            selected.add(pk)
            await query.answer("Added to selection ✅")
        view = context.user_data.get("last_files_view")
        if view:
            await show_files(update, context, view[0], view[1])
        return

    if tag == "fal":
        pks = [f.id for f in course_service.files_in_lecture(pk)]
        label = "lecture"
    elif tag == "fat":
        pks = course_service.file_pks_in_topic(pk)
        label = "topic"
    else:  # fab — every authorized file already mirrored for this batch
        pks = course_service.file_pks_in_batch(pk)
        label = "batch"
    selected.update(pks)
    log_event("INFO", "file_selection", f"scope={label} count={len(pks)}")
    await query.answer(f"Added {len(pks)} file(s) from {label} ✅", show_alert=True)
    if tag == "fal":
        view = context.user_data.get("last_files_view")
        if view:
            await show_files(update, context, view[0], view[1])


@admin_only
async def cb_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]
    selected = _selection(context)

    if action == "clear":
        selected.clear()
        await _edit_or_send(update, "🧹 Selection cleared.",
                            InlineKeyboardMarkup([kb.nav_row(None)]))
        return

    if action == "review":
        if not selected:
            await _edit_or_send(update, "🧺 Selection is empty.\nSelect files first.",
                                InlineKeyboardMarkup([kb.nav_row(None)]))
            return
        videos = pdfs = other = 0
        for pk in selected:
            f = course_service.get_file(pk)
            if f is None:
                continue
            if f.file_type == "video":
                videos += 1
            elif f.file_type == "pdf":
                pdfs += 1
            else:
                other += 1
        dups = upload_service.find_duplicates(list(selected))
        text = ("🧺 Selected:\n\n"
                f"🎥 Videos: {videos}\n📄 PDFs: {pdfs}\n"
                + (f"📁 Other: {other}\n" if other else "")
                + f"Total: {len(selected)}\n")
        if dups:
            example = next(iter(dups.values()))
            text += (f"\n⚠️ Already uploaded: {len(dups)} file(s)\n"
                     f"e.g. Index: {example.index_no}, "
                     f"Telegram Message ID: {example.message_id}\n\n"
                     "Choose how to proceed:")
        await _edit_or_send(update, text, kb.confirm_kb(bool(dups)))
        return

    if action in ("confirm", "skipdup", "updup"):
        if not selected:
            await _edit_or_send(update, "Nothing selected.",
                                InlineKeyboardMarkup([kb.nav_row(None)]))
            return
        pks = list(selected)
        force = False
        if action == "skipdup":
            dups = upload_service.find_duplicates(pks)
            pks = [p for p in pks if p not in dups]
        elif action == "updup":
            force = True
        added = queue_service.enqueue(pks, force=force)
        selected.clear()
        worker = context.application.bot_data.get("upload_worker")
        if worker is not None:
            worker.ensure_running()
        await _edit_or_send(
            update,
            f"📤 Queued {added} file(s) for upload.\n\n"
            "The queue starts automatically. Open 📤 Upload Queue to watch progress.",
            kb.queue_kb(queue_service.is_paused()),
        )


# ============================================================ queue UI
async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    counts = queue_service.queue_counts()
    paused = queue_service.is_paused()
    state = "⏸ PAUSED" if paused else ("📤 Uploading..." if counts["PENDING"]
                                        or counts["UPLOADING"] else "💤 Idle")
    text = (
        f"{state}\n\n"
        f"Total: {counts['TOTAL']}\n"
        f"Completed: {counts['COMPLETED']}\n"
        f"Uploading: {counts['UPLOADING']}\n"
        f"Pending: {counts['PENDING']}\n"
        f"Failed: {counts['FAILED']}\n"
        f"Cancelled: {counts['CANCELLED']}\n\n"
        f"Destination: {get_setting('destination_chat_id', '') or CONFIG.chat_id}"
    )
    await _edit_or_send(update, text, kb.queue_kb(paused))


@admin_only
async def cb_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action = query.data.split(":", 1)[1]
    worker = context.application.bot_data.get("upload_worker")

    if action == "start":
        queue_service.set_paused(False)
        if worker is not None:
            worker.ensure_running()
        await query.answer("▶️ Queue started")
    elif action == "pause":
        queue_service.set_paused(True)
        await query.answer("⏸ Queue paused")
    elif action == "resume":
        queue_service.set_paused(False)
        if worker is not None:
            worker.ensure_running()
        await query.answer("▶️ Queue resumed")
    elif action == "cancel":
        n = queue_service.cancel_pending()
        await query.answer(f"❌ Cancelled {n} pending item(s)", show_alert=True)
    elif action == "retry":
        n = queue_service.retry_failed()
        if worker is not None and n:
            worker.ensure_running()
        await query.answer(f"🔁 Requeued {n} failed item(s)", show_alert=True)
    await show_queue(update, context)


# ============================================================ history
@admin_only
async def cb_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, status_filter, page_s = query.data.split(":")
    page = int(page_s)
    rows = search_service.upload_history(status_filter)
    shown, page, total = paginate(rows, page, per_page=6)
    lines = [f"📜 Upload History — {status_filter.title()} "
             f"({len(rows)} items, page {page + 1}/{total})", ""]
    if not shown:
        lines.append("No entries.")
    for r in shown:
        idx = f"#{r.index_no}" if r.index_no else "—"
        msg = f" | msg {r.message_id}" if r.message_id else ""
        lines.append(
            f"{idx} {file_type_icon(r.file_type)} {truncate(r.title, 45)}\n"
            f"    {truncate(r.batch, 35)} › {truncate(r.topic, 25)}\n"
            f"    {r.status}{msg} | {r.uploaded_at}"
        )
    await _edit_or_send(update, "\n".join(lines),
                        kb.history_kb(status_filter, page, total))


# ============================================================ search
async def run_search(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     query_text: str, page: int = 0) -> None:
    rows = search_service.search_uploads(query_text)
    context.user_data["search_query"] = query_text
    shown, page, total = paginate(rows, page, per_page=6)
    lines = [f"🔍 Results for “{truncate(query_text, 40)}” "
             f"({len(rows)} found, page {page + 1}/{total})", ""]
    if not shown:
        lines.append("No matches.")
    for r in shown:
        msg = f" | msg {r.message_id}" if r.message_id else ""
        lines.append(
            f"#{r.index_no} {file_type_icon(r.file_type)} {truncate(r.title, 45)}\n"
            f"    {truncate(r.batch, 35)} › {truncate(r.topic, 25)}{msg}"
        )
    await _edit_or_send(update, "\n".join(lines), kb.search_kb(page, total))


@admin_only
async def cb_search_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[1])
    q = context.user_data.get("search_query", "")
    if not q:
        await show_main_menu(update, context)
        return
    await run_search(update, context, q, page)


# ============================================================ settings
SETTING_LABELS = {
    "destination_chat_id": "🎯 Destination chat id",
    "caption_template": "📝 Caption template",
    "retry_count": "🔁 Retry count (0-10)",
    "upload_concurrency": "🧵 Upload concurrency (1-3)",
    "notifications": "🔔 Notifications (on/off)",
    "auto_index": "🔢 Auto index (on/off)",
}


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dest = get_setting("destination_chat_id", "") or f"{CONFIG.chat_id} (from .env)"
    text = (
        "⚙️ Settings\n\n"
        f"🎯 Destination: {dest}\n"
        f"📝 Caption template:\n{current_template()}\n\n"
        f"🔁 Retry count: {get_setting('retry_count', '3')}\n"
        f"🧵 Concurrency: {get_setting('upload_concurrency', '1')}\n"
        f"🔔 Notifications: {get_setting('notifications', 'on')}\n"
        f"🔢 Auto index: {get_setting('auto_index', 'on')}\n\n"
        "Placeholders: {index} {title} {topic} {subject} {batch} "
        "{lecture} {file_type} {date}"
    )
    await _edit_or_send(update, text, kb.settings_kb())


@admin_only
async def cb_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    if key not in SETTING_LABELS:
        await show_settings(update, context)
        return
    context.user_data["awaiting"] = ("setting", key)
    await _edit_or_send(
        update,
        f"{SETTING_LABELS[key]}\n\nCurrent value:\n"
        f"{get_setting(key, '') or '(default)'}\n\nSend the new value:",
        InlineKeyboardMarkup([kb.nav_row(None)]),
    )


async def _apply_setting(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         key: str, raw: str) -> None:
    try:
        if key == "destination_chat_id":
            value = validate_chat_id(raw)
            # verify the bot can actually see/post to the chat
            try:
                chat = await context.bot.get_chat(value)
                member = await context.bot.get_chat_member(chat.id, context.bot.id)
                if getattr(member, "can_post_messages", None) is False:
                    raise ValidationError(
                        "Bot has no permission to post in that chat.")
            except TelegramError as exc:
                raise ValidationError(
                    f"Bot cannot access that chat: {exc}. "
                    "Add the bot as admin first.") from exc
        elif key == "caption_template":
            value = validate_caption_template(raw)
        elif key == "retry_count":
            value = str(validate_int_range(raw, 0, 10, "Retry count"))
        elif key == "upload_concurrency":
            value = str(validate_int_range(raw, 1, 3, "Concurrency"))
        elif key in ("notifications", "auto_index"):
            v = raw.strip().lower()
            if v not in ("on", "off"):
                raise ValidationError("Send 'on' or 'off'.")
            value = v
        else:
            raise ValidationError("Unknown setting.")
    except ValidationError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}\nTry again or ❌ Cancel.")
        return

    set_setting(key, value)
    log_event("INFO", "admin_action", f"setting_changed key={key}")
    context.user_data.pop("awaiting", None)
    await update.effective_message.reply_text(f"✅ Saved: {SETTING_LABELS[key]}")
    await show_settings(update, context)


# ============================================================ text router
@admin_only
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles free-text input for search and settings (login has its own
    ConversationHandler that runs first)."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        await update.effective_message.reply_text(
            "Use the menu buttons 🙂 — /start")
        return
    kind, key = awaiting
    if kind == "search":
        try:
            q = validate_search_query(update.effective_message.text)
        except ValidationError as exc:
            await update.effective_message.reply_text(f"⚠️ {exc}")
            return
        context.user_data.pop("awaiting", None)
        await run_search(update, context, q, 0)
    elif kind == "setting":
        await _apply_setting(update, context, key, update.effective_message.text)


# ============================================================ statistics
async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = statistics_service.collect_statistics()
    text = (
        "📊 Statistics\n\n"
        f"Total Batches: {s['batches']}\n"
        f"Total Subjects: {s['subjects']}\n"
        f"Total Topics: {s['topics']}\n"
        f"Total Lectures: {s['lectures']}\n"
        f"Total Files: {s['files']}\n"
        f"🎥 Videos: {s['videos']}\n"
        f"📄 PDFs: {s['pdfs']}\n\n"
        f"✅ Uploaded: {s['uploaded']}\n"
        f"⏳ Pending: {s['pending']}\n"
        f"❌ Failed: {s['failed']}"
    )
    await _edit_or_send(update, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🔃 Refresh", callback_data="m:stats")],
        kb.nav_row(None),
    ]))


# ============================================================ error handler
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler: log details, show a safe message, leak nothing."""
    logger.exception("Unhandled error: %s", context.error)
    log_event("ERROR", "unhandled_error", f"{type(context.error).__name__}")
    try:
        if isinstance(update, Update) and update.effective_user \
                and is_admin(update.effective_user.id) and update.effective_chat:
            await update.effective_chat.send_message(
                "⚠️ Something went wrong. The error was logged.\n/start to continue.")
    except Exception:
        pass


# ============================================================ registration
def build_login_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(login_start, pattern=r"^m:login$")],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                            login_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                            login_password)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
        allow_reentry=True,
    )


def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(build_login_conversation())

    application.add_handler(CallbackQueryHandler(
        cb_menu, pattern=r"^m:(home|cancel|batches|upload|stats|settings|search|logout)$"))
    application.add_handler(CallbackQueryHandler(
        cb_navigation, pattern=r"^(nb|b|ns|s|nt|t|nl|l|nf):"))
    application.add_handler(CallbackQueryHandler(
        cb_file_toggle, pattern=r"^(f|fal|fat|fab):\d+$"))
    application.add_handler(CallbackQueryHandler(cb_selection, pattern=r"^sel:"))
    application.add_handler(CallbackQueryHandler(cb_queue, pattern=r"^q:"))
    application.add_handler(CallbackQueryHandler(cb_history, pattern=r"^h:"))
    application.add_handler(CallbackQueryHandler(cb_search_page, pattern=r"^sr:"))
    application.add_handler(CallbackQueryHandler(cb_settings, pattern=r"^set:"))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)
