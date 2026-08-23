"""NFO sidecar generation for media-library scrapers.

``.nfo`` is the metadata format Kodi / Emby / Jellyfin read to display a
local file with a title, author, plot and thumbnail instead of a bare
filename. It is plain XML sitting next to the media file.

**Why this is not an engine option**: yt-dlp has no NFO writer. Its
``writeinfojson`` emits yt-dlp's *own* JSON schema, which no media
library understands. So ``DownloadOptions.write_nfo`` cannot be a
passthrough — we have to serialize :class:`~doubi.core.models.MediaItem`
ourselves. Since every field we need already lives on the MediaItem,
this stays platform-agnostic and belongs in ``core/storage`` alongside
the manifest writer.

The element set is deliberately minimal and uses only tags that all
three scrapers accept for a ``movie`` entry. We write ``movie`` rather
than ``episode`` because our items are standalone files even when they
come from a collection — an ``episode`` NFO would require a companion
``tvshow.nfo`` and season/episode numbers we cannot always supply.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from ..models import MediaItem

logger = logging.getLogger(__name__)

#: Filename suffix for the sidecar.
NFO_SUFFIX = ".nfo"


def build_nfo_xml(item: MediaItem) -> str:
    """Serialize ``item`` into a Kodi-compatible ``movie`` NFO document.

    Only fields that are actually present are emitted; a scraper treats
    a missing tag as "unknown", whereas an empty tag can make it show a
    blank title, so we skip empties instead of writing them.
    """
    root = ET.Element("movie")

    def _add(tag: str, value: Optional[object]) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        ET.SubElement(root, tag).text = text

    _add("title", item.title)
    _add("originaltitle", item.title)
    # ``plot`` is the description field every scraper shows. Adapters
    # stash the site's description under extra["description"].
    _add("plot", (item.extra or {}).get("description"))
    if item.publish_time is not None:
        _add("premiered", item.publish_time.strftime("%Y-%m-%d"))
        _add("year", item.publish_time.year)
    # Kodi expects runtime in whole minutes, not seconds.
    if item.duration:
        minutes = int(round(float(item.duration) / 60.0))
        if minutes > 0:
            _add("runtime", minutes)
    if item.author and item.author.name:
        # The uploader is the closest analogue to both director and
        # studio for user-generated content; writing both makes the
        # author visible in either scraper layout.
        _add("director", item.author.name)
        _add("studio", item.author.name)
    _add("thumb", item.cover_url)
    _add("source", item.source_url)
    _add("id", item.item_id)
    if item.platform:
        _add("tag", item.platform.value)

    # Declaring the encoding here is what makes the file open correctly
    # in scrapers on Windows, where Chinese titles would otherwise be
    # misread as the system ANSI codepage.
    return ET.tostring(root, encoding="unicode")


def write_nfo(item: MediaItem, target_dir: Path, basename: str) -> Optional[Path]:
    """Write ``item``'s NFO next to its media file.

    ``basename`` must be the same rendered filename stem the engine used
    (``item.output_template``), so the scraper pairs the sidecar with the
    right video. Returns the written path, or ``None`` if writing failed
    — a metadata sidecar must never fail the download itself.
    """
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / (basename + NFO_SUFFIX)
        xml = build_nfo_xml(item)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + xml,
            encoding="utf-8",
        )
        return path
    except OSError:
        logger.warning("could not write NFO for %s", item.item_id, exc_info=True)
        return None
