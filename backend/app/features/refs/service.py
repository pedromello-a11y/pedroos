import uuid
import re
import html
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, delete

from app.features.refs.models import Ref, RefBoard, RefBoardItem
from app.features.refs.schemas import RefCreate, RefUpdate
from app.shared.dates import now_brt


def _short_id() -> str:
    return uuid.uuid4().hex[:6].upper()


def _detect_source_type(url: str) -> tuple[str, str]:
    if not url:
        return ("image", "")
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
    except Exception:
        return ("link", "")

    if "vimeo.com" in domain:
        return ("vimeo", domain)
    if "youtube.com" in domain or "youtu.be" in domain:
        return ("youtube", domain)
    if "instagram.com" in domain:
        return ("instagram", domain)
    if "tiktok.com" in domain:
        return ("tiktok", domain)
    if "behance.net" in domain:
        return ("behance", domain)
    if "dribbble.com" in domain:
        return ("dribbble", domain)
    if "pinterest" in domain:
        return ("pinterest", domain)
    if "figma.com" in domain:
        return ("figma", domain)
    if "twitter.com" in domain or "x.com" in domain:
        return ("twitter", domain)

    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg")):
        return ("image", domain)

    return ("link", domain)


def _youtube_video_id(url: str) -> Optional[str]:
    """Extrai o ID do vídeo de uma URL do YouTube (watch, youtu.be, shorts, embed)."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
        if host == "youtu.be":
            vid = parsed.path.lstrip("/").split("/")[0]
            return vid or None
        if "youtube.com" in host:
            # /watch?v=ID
            m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", url)
            if m:
                return m.group(1)
            # /shorts/ID, /embed/ID, /v/ID
            m = re.match(r"^/(?:shorts|embed|v)/([A-Za-z0-9_-]{6,})", parsed.path)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


async def _extract_youtube(url: str) -> dict:
    """YouTube: thumb via URL direta (sem API). Título via oEmbed (público, sem auth)."""
    out: dict = {}
    vid = _youtube_video_id(url)
    if not vid:
        return out
    out["thumbnail"] = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
            r = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("title"):
                    out["title"] = str(data["title"])[:200]
                if data.get("thumbnail_url"):
                    out["thumbnail"] = data["thumbnail_url"]
    except Exception:
        pass
    return out


def _instagram_shortcode(url: str) -> Optional[str]:
    """Extrai shortcode de URLs /p/{code}/, /reel/{code}/, /tv/{code}/."""
    try:
        parsed = urlparse(url)
        m = re.match(r"^/(?:p|reel|tv|reels)/([A-Za-z0-9_-]+)", parsed.path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


async def _extract_instagram(url: str) -> dict:
    """Scraping do endpoint /embed/captioned/ — público, sem auth.

    Instagram pode quebrar isso a qualquer momento (não é API documentada).
    Quando quebra, cai no placeholder com gradient colorido.
    """
    out: dict = {}
    shortcode = _instagram_shortcode(url)
    if not shortcode:
        return out
    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            r = await client.get(
                embed_url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            )
            if r.status_code != 200:
                return out
            page = r.text[:80000]

        # OG image: o próprio frame do post hospedado no CDN do Instagram
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', page, re.I)
        if m:
            out["thumbnail"] = html.unescape(m.group(1).strip())

        # OG title vem como "Username on Instagram: ..."
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', page, re.I)
        if m:
            out["title"] = html.unescape(m.group(1).strip())[:200]

        # Fallback: imagem dentro do embed quando OG falha
        if not out.get("thumbnail"):
            m = re.search(r'class="EmbeddedMediaImage"[^>]+src="([^"]+)"', page, re.I)
            if m:
                out["thumbnail"] = html.unescape(m.group(1).strip())
    except Exception:
        pass
    return out


async def _extract_vimeo(url: str) -> dict:
    """Vimeo: oEmbed retorna title + thumbnail_url (frame escolhido pelo dono)."""
    out: dict = {}
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
            r = await client.get(
                "https://vimeo.com/api/oembed.json",
                params={"url": url},
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("title"):
                    out["title"] = str(data["title"])[:200]
                if data.get("thumbnail_url"):
                    out["thumbnail"] = data["thumbnail_url"]
    except Exception:
        pass
    return out


async def extract_metadata(url: str) -> dict:
    result: dict = {"title": None, "thumbnail": None}
    source_type, domain = _detect_source_type(url)
    result["source_type"] = source_type
    result["domain"] = domain

    # Platform-specific extractors (mais confiáveis que OG scraping)
    if source_type == "youtube":
        result.update(await _extract_youtube(url))
        if result.get("title") and result.get("thumbnail"):
            return result
    elif source_type == "vimeo":
        result.update(await _extract_vimeo(url))
        if result.get("title") and result.get("thumbnail"):
            return result
    elif source_type == "instagram":
        result.update(await _extract_instagram(url))
        if result.get("title") and result.get("thumbnail"):
            return result

    # Fallback: scrape OG tags
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return result
            html_text = resp.text[:50000]

        if not result.get("title"):
            m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html_text, re.I)
            if not m:
                m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html_text, re.I)
            if m:
                result["title"] = html.unescape(m.group(1).strip())[:200]
            else:
                m = re.search(r'<title[^>]*>([^<]+)</title>', html_text, re.I)
                if m:
                    result["title"] = html.unescape(m.group(1).strip())[:200]

        if not result.get("thumbnail"):
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_text, re.I)
            if not m:
                m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html_text, re.I)
            if m:
                result["thumbnail"] = html.unescape(m.group(1).strip())

    except Exception:
        pass

    return result


async def _get_or_create_board(db: AsyncSession, name: str) -> RefBoard:
    name_lower = name.strip().lower()
    result = await db.execute(
        select(RefBoard).where(func.lower(RefBoard.name) == name_lower)
    )
    board = result.scalar_one_or_none()
    if board:
        return board

    max_pos = await db.execute(select(func.max(RefBoard.position)))
    pos = (max_pos.scalar() or 0) + 1

    board = RefBoard(
        id=str(uuid.uuid4()),
        name=name.strip(),
        color=None,
        position=pos,
        created_at=now_brt().isoformat(),
    )
    db.add(board)
    await db.flush()
    return board


async def create_ref(db: AsyncSession, data: RefCreate) -> Ref:
    now = now_brt().isoformat()

    source_type = data.source_type
    domain = ""
    if data.url and not source_type:
        source_type, domain = _detect_source_type(data.url)
    elif not data.url:
        source_type = source_type or "image"

    ref = Ref(
        id=str(uuid.uuid4()),
        short_id=_short_id(),
        url=data.url,
        title=data.title,
        note=data.note,
        thumbnail=data.thumbnail,
        source_type=source_type,
        domain=domain,
        raw_input=data.raw_input,
        source=data.source,
        created_at=now,
        updated_at=now,
    )
    db.add(ref)
    await db.flush()

    for board_name in data.boards:
        if not board_name.strip():
            continue
        board = await _get_or_create_board(db, board_name)
        db.add(RefBoardItem(ref_id=ref.id, board_id=board.id, position=0, added_at=now))

    await db.commit()
    await db.refresh(ref)
    return ref


async def list_refs(
    db: AsyncSession,
    source_type: Optional[str] = None,
    q: Optional[str] = None,
    uncategorized: bool = False,
    board: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Ref], int]:
    query = select(Ref)
    count_query = select(func.count(Ref.id))

    if uncategorized:
        has_board = select(RefBoardItem.ref_id)
        query = query.where(Ref.id.notin_(has_board))
        count_query = count_query.where(Ref.id.notin_(has_board))
    elif board:
        board_sub = (
            select(RefBoardItem.ref_id)
            .join(RefBoard, RefBoard.id == RefBoardItem.board_id)
            .where(func.lower(RefBoard.name) == board.lower())
        )
        query = query.where(Ref.id.in_(board_sub))
        count_query = count_query.where(Ref.id.in_(board_sub))

    if source_type:
        query = query.where(Ref.source_type == source_type)
        count_query = count_query.where(Ref.source_type == source_type)

    if q:
        like = f"%{q}%"
        filt = or_(
            Ref.title.ilike(like),
            Ref.note.ilike(like),
            Ref.url.ilike(like),
            Ref.domain.ilike(like),
        )
        query = query.where(filt)
        count_query = count_query.where(filt)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Ref.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_ref(db: AsyncSession, ref_id: str) -> Optional[Ref]:
    result = await db.execute(select(Ref).where(Ref.id == ref_id))
    ref = result.scalar_one_or_none()
    if not ref:
        result = await db.execute(select(Ref).where(Ref.short_id == ref_id))
        ref = result.scalar_one_or_none()
    return ref


async def get_ref_boards(db: AsyncSession, ref_id: str) -> list[str]:
    result = await db.execute(
        select(RefBoard.name)
        .join(RefBoardItem, RefBoard.id == RefBoardItem.board_id)
        .where(RefBoardItem.ref_id == ref_id)
    )
    return [row[0] for row in result.all()]


async def update_ref(db: AsyncSession, ref_id: str, data: RefUpdate) -> Optional[Ref]:
    ref = await get_ref(db, ref_id)
    if not ref:
        return None

    if data.title is not None:
        ref.title = data.title
    if data.note is not None:
        ref.note = data.note
    if data.thumbnail is not None:
        ref.thumbnail = data.thumbnail
    ref.updated_at = now_brt().isoformat()

    if data.boards is not None:
        await db.execute(delete(RefBoardItem).where(RefBoardItem.ref_id == ref.id))
        now = now_brt().isoformat()
        for board_name in data.boards:
            if not board_name.strip():
                continue
            board = await _get_or_create_board(db, board_name)
            db.add(RefBoardItem(ref_id=ref.id, board_id=board.id, position=0, added_at=now))

    await db.commit()
    await db.refresh(ref)
    return ref


async def delete_ref(db: AsyncSession, ref_id: str) -> bool:
    ref = await get_ref(db, ref_id)
    if not ref:
        return False
    await db.execute(delete(RefBoardItem).where(RefBoardItem.ref_id == ref.id))
    await db.delete(ref)
    await db.commit()
    return True


async def add_ref_to_board(db: AsyncSession, ref_id: str, board_name: str) -> bool:
    ref = await get_ref(db, ref_id)
    if not ref:
        return False
    board = await _get_or_create_board(db, board_name)
    existing = await db.execute(
        select(RefBoardItem).where(
            RefBoardItem.ref_id == ref.id,
            RefBoardItem.board_id == board.id,
        )
    )
    if existing.scalar_one_or_none():
        return True
    db.add(RefBoardItem(ref_id=ref.id, board_id=board.id, position=0, added_at=now_brt().isoformat()))
    await db.commit()
    return True


async def remove_ref_from_board(db: AsyncSession, ref_id: str, board_id: str) -> bool:
    result = await db.execute(
        select(RefBoardItem).where(
            RefBoardItem.ref_id == ref_id,
            RefBoardItem.board_id == board_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return False
    await db.delete(item)
    await db.commit()
    return True


# ── Boards CRUD ─────────────────────────────────────────────────────────────

async def list_boards(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(RefBoard).order_by(RefBoard.position))
    boards = result.scalars().all()

    output = []
    for board in boards:
        count_res = await db.execute(
            select(func.count(RefBoardItem.ref_id)).where(RefBoardItem.board_id == board.id)
        )
        count = count_res.scalar() or 0
        output.append({
            "id": board.id,
            "name": board.name,
            "color": board.color,
            "position": board.position,
            "count": count,
            "created_at": board.created_at,
        })

    has_board = select(RefBoardItem.ref_id)
    uncat_res = await db.execute(
        select(func.count(Ref.id)).where(Ref.id.notin_(has_board))
    )
    uncat_count = uncat_res.scalar() or 0
    output.append({
        "id": "__uncategorized__",
        "name": "Inbox",
        "color": "#475569",
        "position": 9999,
        "count": uncat_count,
        "created_at": "",
    })

    return output


async def create_board(db: AsyncSession, name: str, color: Optional[str] = None) -> RefBoard:
    board = await _get_or_create_board(db, name)
    if color:
        board.color = color
        await db.commit()
        await db.refresh(board)
    return board


async def update_board(
    db: AsyncSession,
    board_id: str,
    name: Optional[str] = None,
    color: Optional[str] = None,
    position: Optional[int] = None,
) -> Optional[RefBoard]:
    result = await db.execute(select(RefBoard).where(RefBoard.id == board_id))
    board = result.scalar_one_or_none()
    if not board:
        return None
    if name is not None:
        board.name = name
    if color is not None:
        board.color = color
    if position is not None:
        board.position = position
    await db.commit()
    await db.refresh(board)
    return board


async def delete_board(db: AsyncSession, board_id: str) -> bool:
    result = await db.execute(select(RefBoard).where(RefBoard.id == board_id))
    board = result.scalar_one_or_none()
    if not board:
        return False
    await db.execute(delete(RefBoardItem).where(RefBoardItem.board_id == board.id))
    await db.delete(board)
    await db.commit()
    return True
