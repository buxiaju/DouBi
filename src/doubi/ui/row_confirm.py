"""Confirmation copy for *batch* row actions on the search / hot pages.

Right-clicking a row whose target is a **container** (a 热搜词, or a
B 站 user hit) does not download "one thing" — it fans out into many
downloads. 0.3.6 shipped that behaviour with an ambiguous menu label
(「下载」) and no pre-flight confirmation, so a single click on the hot
word 「亚运会国足夺铜牌」 quietly queued 20 videos. That reads as a bug
even though the fan-out is the intended semantics for a word.

This module holds the *decision* — what to ask, and with which title /
body / button labels — as pure functions over plain values:

* no Qt, so it is unit-testable without a ``QApplication`` and therefore
  still runs under the ``ci`` profile where PySide6 is blocked;
* no network, so the wording can be asserted verbatim.

The page keeps only the plumbing: call :func:`confirm_plan` after the
count is known, then render the returned text into a ``QMessageBox``.

Splitting it this way also fixes the ordering problem: for a 热搜词 the
count is only knowable *after* the search, so the page must search first
and confirm second. :func:`confirm_plan` is therefore written to take an
already-resolved ``count`` rather than guessing an estimate up front.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Menu label for a 热搜词 row. Deliberately verbose: the previous
#: 「下载」 was read as "download this one row", which is what caused the
#: surprise. A word has no single downloadable target, so the label has
#: to describe the fan-out itself.
HOT_WORD_ACTION = "搜索该词并下载全部视频"

#: Menu label for a container row that expands into children (B 站 user
#: hits / any row whose URL parses to USER or MIX).
CONTAINER_ACTION = "下载（展开全部）"

#: Action-bar button label for the multi-select batch download mode
#: (0.3.14 移植自 BiliMusic-Desktop 的「多选整理」交互：B 站收藏夹/
#: 搜索结果经常要一次收好几条，右键逐条下载效率太低)。
MULTI_SELECT_ACTION = "批量下载选中项"


def confirm_multi_select_plan(count: int, skipped: int = 0) -> ConfirmPlan:
    """Confirmation for queuing every checked row of the search / hot table.

    :param count: rows that resolved to a downloadable target.
    :param skipped: rows that could not be resolved (no URL / hot-word
        rows / parse failures) — mentioned in the body so the number on
        the dialog matches what actually gets queued.
    """
    lines = [
        f"已选中 {count} 项，将逐条解析并加入下载队列。",
    ]
    if skipped > 0:
        lines.append(
            f"另有 {skipped} 项无法下载（热搜词或没有直链），已跳过。"
        )
    lines.append(
        "容器类内容（用户主页 / 合集）会展开为多条视频，实际下载数可能更多。"
    )
    return ConfirmPlan(
        title="批量下载",
        body="\n\n".join(lines),
        confirmed_text="全部下载",
        cancelled_text="取消",
    )
@dataclass(frozen=True)
class ConfirmPlan:
    """A ready-to-render confirmation dialog.

    ``confirmed_text`` / ``cancelled_text`` are the two button labels;
    the page maps them onto ``QMessageBox`` buttons in that order so the
    destructive-ish choice is never the default.
    """

    title: str
    body: str
    confirmed_text: str = "继续"
    cancelled_text: str = "取消"


def confirm_plan(
    *, kind: str, label: str, count: Optional[int] = None
) -> ConfirmPlan:
    """Build the confirmation for a fan-out action.

    :param kind: ``"hot_word"`` (search the word, queue every hit) or
        ``"container"`` (expand a container row into its children).
    :param label: human-readable row label (the word / the user name).
        Blank falls back to a generic subject so the dialog never renders
        an empty quotation.
    :param count: how many items the fan-out will produce. ``None`` when
        it is not known yet — the page searches first precisely so this
        is a real number rather than an estimate.
    """
    subject = (label or "").strip() or "该词条"

    if kind == "hot_word":
        if count is None:
            body = (
                f"将搜索「{subject}」，并把搜到的视频全部加入下载队列。\n\n"
                f"词条本身没有可直接下载的内容，所以这里下载的是搜索结果，"
                f"数量取决于平台返回多少条。"
            )
        else:
            body = (
                f"已搜索「{subject}」，共搜到 {count} 个视频。\n\n"
                f"全部加入下载队列？\n\n"
                f"词条本身没有可直接下载的内容，所以下载的是搜索结果。"
            )
        return ConfirmPlan(title="搜索该词并下载全部视频", body=body)

    if kind == "container":
        if count is None:
            body = (
                f"「{subject}」是一个合集 / 主页，不是一个单独的视频。\n\n"
                f"下载它会把里面的内容全部展开，可能包含很多个视频。"
            )
        else:
            body = (
                f"「{subject}」是一个合集 / 主页，不是一个单独的视频。\n\n"
                f"下载它会展开出 {count} 个视频并全部加入下载队列。"
            )
        return ConfirmPlan(title="下载合集 / 主页", body=body)

    raise ValueError(f"unknown confirm kind: {kind!r}")


def container_is_batch(item, children) -> bool:
    """True when *item* would fan out into more than one download.

    The two ways a row can do that, both of which need a confirmation:

    * ``children`` is non-empty — the URL parsed into a container and the
      children were attached eagerly (B 站 section / episode containers);
    * ``item`` is a COLLECTION / FAVLIST / USER / MIX — a container whose
      children are *not* attached yet, which the pipeline expands on its
      own (this is the B 站 user-hit case).

    Mirrors :meth:`MediaItem.needs_expansion` on the model side rather
    than re-deriving it, so the two cannot drift.
    """
    if item is None:
        return False
    if children:
        return True
    needs = getattr(item, "needs_expansion", None)
    if callable(needs):
        try:
            return bool(needs())
        except Exception:  # noqa: BLE001 - a probe must never break the UI
            return False
    return False


def expected_count(item, children) -> Optional[int]:
    """Best-effort item count for the confirmation body.

    Returns ``len(children)`` when they are attached, else ``None`` —
    an unattached container's real size is only known after expansion, so
    we say "many" instead of inventing a number.
    """
    if children:
        return len(children)
    return None
