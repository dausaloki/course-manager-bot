"""Inline keyboard builders with pagination.

Callback-data grammar (always < 64 bytes):
  m:<action>            main menu actions
  nb:<page>             batches list page
  b:<pk>                open batch
  ns:<batch>:<page>     subjects page        s:<pk>  open subject
  nt:<subj>:<page>      topics page          t:<pk>  open topic
  nl:<topic>:<page>     lectures page        l:<pk>  open lecture
  nf:<lect>:<page>      files page           f:<pk>  toggle file selection
  fal/fat/fab:<pk>      select all in lecture/topic/batch
  sel:<action>          selection & confirmation
  q:<action>            queue control
  h:<filter>:<page>     history
  sr:<page>             search results page
  set:<key>             settings edit
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.helpers import PER_PAGE, file_type_icon, paginate, truncate

BTN_BACK = "⬅️ Back"
BTN_HOME = "🏠 Home"
BTN_CANCEL = "❌ Cancel"


def nav_row(back_cb: str | None) -> list[InlineKeyboardButton]:
    row = []
    if back_cb:
        row.append(InlineKeyboardButton(BTN_BACK, callback_data=back_cb))
    row.append(InlineKeyboardButton(BTN_HOME, callback_data="m:home"))
    row.append(InlineKeyboardButton(BTN_CANCEL, callback_data="m:cancel"))
    return row


def page_row(prefix: str, page: int, total_pages: int) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"{prefix}:{page - 1}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton("➡️ Next", callback_data=f"{prefix}:{page + 1}"))
    return row


def main_menu(logged_in: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔐 Login" if not logged_in else "🔐 Re-Login",
                              callback_data="m:login"),
         InlineKeyboardButton("📚 My Batches", callback_data="m:batches")],
        [InlineKeyboardButton("📤 Upload Queue", callback_data="m:upload"),
         InlineKeyboardButton("📜 Upload History", callback_data="h:ALL:0")],
        [InlineKeyboardButton("🔍 Search", callback_data="m:search"),
         InlineKeyboardButton("📊 Statistics", callback_data="m:stats")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="m:settings"),
         InlineKeyboardButton("🔄 Retry Failed", callback_data="q:retry")],
    ]
    if logged_in:
        rows.append([InlineKeyboardButton("🚪 Logout", callback_data="m:logout")])
    return InlineKeyboardMarkup(rows)


def batches_kb(batches: list, page: int) -> tuple[InlineKeyboardMarkup, int, int]:
    items, page, total = paginate(batches, page)
    rows = [[InlineKeyboardButton(f"{i + 1 + page * PER_PAGE}️⃣ {truncate(b.name, 44)}",
                                  callback_data=f"b:{b.id}")]
            for i, b in enumerate(items)]
    pr = page_row("nb", page, total)
    if pr:
        rows.append(pr)
    rows.append(nav_row(None))
    return InlineKeyboardMarkup(rows), page, total


def subjects_kb(batch_pk: int, subjects: list, page: int) -> InlineKeyboardMarkup:
    items, page, total = paginate(subjects, page)
    rows = [[InlineKeyboardButton(f"📘 {truncate(s.name, 44)}", callback_data=f"s:{s.id}")]
            for s in items]
    pr = page_row(f"ns:{batch_pk}", page, total)
    if pr:
        rows.append(pr)
    rows.append([InlineKeyboardButton("☑️ Select ALL files in batch",
                                      callback_data=f"fab:{batch_pk}")])
    rows.append(nav_row("nb:0"))
    return InlineKeyboardMarkup(rows)


def topics_kb(batch_pk: int, subject_pk: int, topics: list, page: int) -> InlineKeyboardMarkup:
    items, page, total = paginate(topics, page)
    rows = [[InlineKeyboardButton(f"📂 {truncate(t.name, 44)}", callback_data=f"t:{t.id}")]
            for t in items]
    pr = page_row(f"nt:{subject_pk}", page, total)
    if pr:
        rows.append(pr)
    rows.append(nav_row(f"b:{batch_pk}"))
    return InlineKeyboardMarkup(rows)


def lectures_kb(subject_pk: int, topic_pk: int, lectures: list, page: int) -> InlineKeyboardMarkup:
    items, page, total = paginate(lectures, page)
    rows = [[InlineKeyboardButton(f"🎓 {truncate(l.name, 44)}", callback_data=f"l:{l.id}")]
            for l in items]
    pr = page_row(f"nl:{topic_pk}", page, total)
    if pr:
        rows.append(pr)
    rows.append([InlineKeyboardButton("☑️ Select ALL files in topic",
                                      callback_data=f"fat:{topic_pk}")])
    rows.append(nav_row(f"s:{subject_pk}"))
    return InlineKeyboardMarkup(rows)


def files_kb(topic_pk: int, lecture_pk: int, files: list, selected: set[int],
             page: int) -> InlineKeyboardMarkup:
    items, page, total = paginate(files, page)
    rows = []
    for f in items:
        mark = "✅ " if f.id in selected else ""
        icon = file_type_icon(f.file_type)
        rows.append([InlineKeyboardButton(
            f"{mark}{icon} {truncate(f.title, 40)}", callback_data=f"f:{f.id}")])
    pr = page_row(f"nf:{lecture_pk}", page, total)
    if pr:
        rows.append(pr)
    rows.append([InlineKeyboardButton("☑️ Select ALL in lecture",
                                      callback_data=f"fal:{lecture_pk}")])
    rows.append([InlineKeyboardButton("🧺 Review selection", callback_data="sel:review"),
                 InlineKeyboardButton("🧹 Clear", callback_data="sel:clear")])
    rows.append(nav_row(f"t:{topic_pk}"))
    return InlineKeyboardMarkup(rows)


def confirm_kb(has_duplicates: bool) -> InlineKeyboardMarkup:
    if has_duplicates:
        rows = [
            [InlineKeyboardButton("⏭ Skip duplicates & upload rest",
                                  callback_data="sel:skipdup")],
            [InlineKeyboardButton("🔄 Upload Again (incl. duplicates)",
                                  callback_data="sel:updup")],
            [InlineKeyboardButton("❌ Cancel", callback_data="m:home")],
        ]
    else:
        rows = [
            [InlineKeyboardButton("✅ Confirm Upload", callback_data="sel:confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="m:home")],
        ]
    return InlineKeyboardMarkup(rows)


def queue_kb(paused: bool) -> InlineKeyboardMarkup:
    toggle = InlineKeyboardButton("▶️ Resume", callback_data="q:resume") if paused \
        else InlineKeyboardButton("⏸ Pause", callback_data="q:pause")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start", callback_data="q:start"), toggle],
        [InlineKeyboardButton("🔁 Retry Failed", callback_data="q:retry"),
         InlineKeyboardButton("❌ Cancel pending", callback_data="q:cancel")],
        [InlineKeyboardButton("🔃 Refresh", callback_data="m:upload"),
         InlineKeyboardButton("📜 View History", callback_data="h:ALL:0")],
        nav_row(None),
    ])


def history_kb(status_filter: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    filters = ["ALL", "COMPLETED", "FAILED", "PENDING"]
    filter_row = [
        InlineKeyboardButton(("• " if f == status_filter else "") + f.title(),
                             callback_data=f"h:{f}:0")
        for f in filters
    ]
    rows = [filter_row]
    pr = page_row(f"h:{status_filter}", page, total_pages)
    if pr:
        rows.append(pr)
    rows.append(nav_row(None))
    return InlineKeyboardMarkup(rows)


def search_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    pr = page_row("sr", page, total_pages)
    if pr:
        rows.append(pr)
    rows.append([InlineKeyboardButton("🔍 New search", callback_data="m:search")])
    rows.append(nav_row(None))
    return InlineKeyboardMarkup(rows)


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Destination chat", callback_data="set:destination_chat_id")],
        [InlineKeyboardButton("📝 Caption template", callback_data="set:caption_template")],
        [InlineKeyboardButton("🔁 Retry count", callback_data="set:retry_count"),
         InlineKeyboardButton("🧵 Concurrency", callback_data="set:upload_concurrency")],
        [InlineKeyboardButton("🔔 Notifications", callback_data="set:notifications"),
         InlineKeyboardButton("🔢 Auto index", callback_data="set:auto_index")],
        nav_row(None),
    ])
