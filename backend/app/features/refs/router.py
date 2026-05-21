from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import os
import uuid

import httpx

from app.db import get_db
from app.features.refs import service
from app.features.refs.schemas import (
    RefCreate, RefUpdate, RefResponse,
    RefBoardCreate, RefBoardUpdate,
    ExtractResponse,
)

router = APIRouter(prefix="/api/refs", tags=["refs"])
boards_router = APIRouter(prefix="/api/ref-boards", tags=["ref-boards"])

UPLOADS_DIR = os.environ.get("UPLOADS_DIR") or str(
    Path(__file__).parent.parent.parent.parent / "data" / "uploads"
)


async def _ref_to_response(db, ref) -> RefResponse:
    boards = await service.get_ref_boards(db, ref.id)
    return RefResponse(
        id=ref.id,
        short_id=ref.short_id,
        url=ref.url,
        title=ref.title,
        note=ref.note,
        thumbnail=ref.thumbnail,
        source_type=ref.source_type,
        domain=ref.domain,
        source=ref.source,
        boards=boards,
        created_at=ref.created_at,
        updated_at=ref.updated_at,
    )


# ── Fixed routes first (must come before /{ref_id}) ─────────────────────────

@router.post("/extract")
async def extract_url(data: dict, db: AsyncSession = Depends(get_db)):
    url = data.get("url", "")
    if not url:
        raise HTTPException(400, "URL obrigatória")
    meta = await service.extract_metadata(url)
    return ExtractResponse(**meta)


@router.get("/img-proxy")
async def img_proxy(url: str = Query(...)):
    """Proxy de imagem com Referer correto para CDNs que bloqueiam hotlink."""
    if not url.startswith("http"):
        raise HTTPException(400, "URL inválida")
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.instagram.com/",
            })
        if r.status_code != 200:
            raise HTTPException(502, "Imagem indisponível")
        ctype = r.headers.get("content-type", "image/jpeg")
        return Response(content=r.content, media_type=ctype, headers={
            "Cache-Control": "public, max-age=86400",
        })
    except httpx.RequestError:
        raise HTTPException(502, "Erro ao buscar imagem")


@router.post("/upload", status_code=201)
async def upload_ref_image(
    file: UploadFile = File(...),
    note: Optional[str] = None,
    boards: Optional[str] = None,
    url: Optional[str] = None,
    title: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Sobe imagem como thumb. Se url for passada, vira ref desse link com a imagem
    como thumbnail (caso clássico: screenshot de post do Instagram + link do post)."""
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    stored = f"ref_{uuid.uuid4().hex[:12]}{ext}"
    content = await file.read()
    with open(os.path.join(UPLOADS_DIR, stored), "wb") as f:
        f.write(content)

    thumbnail_path = f"/uploads/{stored}"
    board_list = [b.strip() for b in (boards or "").split(",") if b.strip()]

    # Se tem URL e não tem título, tenta extrair título da página
    final_title = title or file.filename
    source_type = "image"
    if url:
        source_type = None  # detect from URL
        if not title:
            meta = await service.extract_metadata(url)
            if meta.get("title"):
                final_title = meta["title"]

    data_obj = RefCreate(
        url=url,
        title=final_title,
        note=note,
        thumbnail=thumbnail_path,
        source_type=source_type,
        boards=board_list,
        source="dashboard",
    )
    ref = await service.create_ref(db, data_obj)
    return await _ref_to_response(db, ref)


# ── Collection routes ────────────────────────────────────────────────────────

@router.get("")
async def list_refs(
    board: Optional[str] = Query(None),
    uncategorized: bool = Query(False),
    source_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    refs, total = await service.list_refs(
        db,
        board=board,
        uncategorized=uncategorized,
        source_type=source_type,
        q=q,
        limit=limit,
        offset=offset,
    )
    items = [await _ref_to_response(db, ref) for ref in refs]
    return {"items": items, "total": total}


@router.post("", status_code=201)
async def create_ref(data: RefCreate, db: AsyncSession = Depends(get_db)):
    if data.url and (not data.title or not data.thumbnail):
        meta = await service.extract_metadata(data.url)
        if not data.title and meta.get("title"):
            data.title = meta["title"]
        if not data.thumbnail and meta.get("thumbnail"):
            data.thumbnail = meta["thumbnail"]
        if not data.source_type and meta.get("source_type"):
            data.source_type = meta["source_type"]

    ref = await service.create_ref(db, data)
    return await _ref_to_response(db, ref)


# ── Item routes ──────────────────────────────────────────────────────────────

@router.get("/{ref_id}")
async def get_ref(ref_id: str, db: AsyncSession = Depends(get_db)):
    ref = await service.get_ref(db, ref_id)
    if not ref:
        raise HTTPException(404, "Ref não encontrada")
    return await _ref_to_response(db, ref)


@router.patch("/{ref_id}")
async def update_ref(ref_id: str, data: RefUpdate, db: AsyncSession = Depends(get_db)):
    ref = await service.update_ref(db, ref_id, data)
    if not ref:
        raise HTTPException(404, "Ref não encontrada")
    return await _ref_to_response(db, ref)


@router.delete("/{ref_id}", status_code=204)
async def delete_ref(ref_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_ref(db, ref_id):
        raise HTTPException(404, "Ref não encontrada")


@router.post("/{ref_id}/refresh-thumb")
async def refresh_thumb(ref_id: str, db: AsyncSession = Depends(get_db)):
    """Re-extrai metadata da URL e baixa nova thumb localmente.
    Útil pra refs antigas cuja thumb expirou (CDN do Instagram)."""
    ref = await service.get_ref(db, ref_id)
    if not ref:
        raise HTTPException(404, "Ref não encontrada")
    if not ref.url:
        raise HTTPException(400, "Ref sem URL — não dá pra re-extrair")
    meta = await service.extract_metadata(ref.url)
    new_thumb = meta.get("thumbnail")
    if new_thumb and new_thumb.startswith("http") and service._is_volatile_thumb(new_thumb):
        local = await service._download_thumb(new_thumb)
        if local:
            new_thumb = local
    if new_thumb:
        ref.thumbnail = new_thumb
    if meta.get("title") and not ref.title:
        ref.title = meta["title"]
    from app.shared.dates import now_brt
    ref.updated_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(ref)
    return await _ref_to_response(db, ref)


@router.post("/{ref_id}/boards")
async def add_to_board(ref_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    board_name = data.get("board")
    if not board_name:
        raise HTTPException(400, "Campo 'board' obrigatório")
    if not await service.add_ref_to_board(db, ref_id, board_name):
        raise HTTPException(404, "Ref não encontrada")
    return {"ok": True}


@router.delete("/{ref_id}/boards/{board_id}", status_code=204)
async def remove_from_board(ref_id: str, board_id: str, db: AsyncSession = Depends(get_db)):
    await service.remove_ref_from_board(db, ref_id, board_id)


# ── Boards ───────────────────────────────────────────────────────────────────

@boards_router.get("")
async def list_boards(db: AsyncSession = Depends(get_db)):
    return await service.list_boards(db)


@boards_router.post("", status_code=201)
async def create_board(data: RefBoardCreate, db: AsyncSession = Depends(get_db)):
    board = await service.create_board(db, data.name, data.color)
    return {"id": board.id, "name": board.name, "color": board.color, "position": board.position}


@boards_router.patch("/{board_id}")
async def update_board(board_id: str, data: RefBoardUpdate, db: AsyncSession = Depends(get_db)):
    board = await service.update_board(db, board_id, data.name, data.color, data.position)
    if not board:
        raise HTTPException(404, "Board não encontrado")
    return {"id": board.id, "name": board.name, "color": board.color, "position": board.position}


@boards_router.delete("/{board_id}", status_code=204)
async def delete_board(board_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_board(db, board_id):
        raise HTTPException(404, "Board não encontrado")
