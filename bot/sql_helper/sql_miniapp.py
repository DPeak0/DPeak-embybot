"""
MiniApp 数据库模型
- MiniAppRequest: 用户求片记录
"""
from datetime import datetime
from typing import Optional, List
from bot.sql_helper import Base, Session, engine
from sqlalchemy import Column, BigInteger, String, DateTime, Integer, Text, SmallInteger, text
from bot import LOGGER


class MiniAppRequest(Base):
    """
    求片申请表
    status: pending(待处理) / processing(处理中) / completed(已入库) / rejected(已拒绝)
    """
    __tablename__ = 'miniapp_requests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg = Column(BigInteger, nullable=False, index=True)
    tmdb_id = Column(String(20), nullable=True)
    media_type = Column(String(10), nullable=True)       # 'movie' | 'tv'
    title = Column(String(500), nullable=True)
    orig_title = Column(String(500), nullable=True)
    poster = Column(String(500), nullable=True)
    year = Column(String(10), nullable=True)
    status = Column(String(20), default='pending')
    note = Column(Text, nullable=True)        # 管理员备注（旧字段保留）
    user_note = Column(Text, nullable=True)   # 用户备注（新字段）
    notified = Column(SmallInteger, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


MiniAppRequest.__table__.create(bind=engine, checkfirst=True)


def _migrate_add_user_note():
    """迁移：若 user_note 列不存在则自动添加（兼容 MySQL 5.7+）"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='miniapp_requests' AND COLUMN_NAME='user_note'"
            ))
            if result.scalar() == 0:
                conn.execute(text(
                    "ALTER TABLE miniapp_requests ADD COLUMN user_note TEXT NULL DEFAULT NULL"
                ))
                conn.commit()
                LOGGER.info("【MiniApp迁移】已添加 user_note 列")
    except Exception as e:
        LOGGER.error(f"【MiniApp迁移】添加 user_note 列失败: {e}")


_migrate_add_user_note()


# ── 求片 CRUD ──────────────────────────────────────────────────────────────────

def sql_add_request(tg: int, tmdb_id: str, media_type: str, title: str,
                    orig_title: str, poster: str, year: str,
                    user_note: str = ""):
    """
    新增求片申请。
    返回值：
      MiniAppRequest  → 新建成功
      "completed"     → 该影片已入库，不可重复申请
      None            → 已存在 pending/processing 申请
    """
    with Session() as session:
        try:
            # 检查是否已入库
            completed = session.query(MiniAppRequest).filter(
                MiniAppRequest.tg == tg,
                MiniAppRequest.tmdb_id == tmdb_id,
                MiniAppRequest.status == 'completed',
            ).first()
            if completed:
                return "completed"

            # 检查是否存在待处理申请
            exist = session.query(MiniAppRequest).filter(
                MiniAppRequest.tg == tg,
                MiniAppRequest.tmdb_id == tmdb_id,
                MiniAppRequest.status.in_(['pending', 'processing'])
            ).first()
            if exist:
                return None

            req = MiniAppRequest(
                tg=tg, tmdb_id=tmdb_id, media_type=media_type,
                title=title, orig_title=orig_title, poster=poster, year=year,
                user_note=user_note or None,
            )
            session.add(req)
            session.commit()
            session.refresh(req)
            return req
        except Exception as e:
            LOGGER.error(f"【MiniApp】新增求片申请失败: {e}")
            session.rollback()
            return None


def sql_get_requests_by_tg(tg: int, limit: int = 20) -> list:
    """查询用户所有求片申请（最近 limit 条）"""
    with Session() as session:
        try:
            rows = session.query(MiniAppRequest).filter(
                MiniAppRequest.tg == tg
            ).order_by(MiniAppRequest.created_at.desc()).limit(limit).all()
            return [_request_to_dict(r) for r in rows]
        except Exception as e:
            LOGGER.error(f"【MiniApp】查询求片申请失败: {e}")
            return []


def sql_get_requests_status_map(tg: int) -> dict:
    """
    返回该用户所有申请的 {tmdb_id: status} 字典，供前端初始化按钮状态。
    同一 tmdb_id 有多条记录时，取优先级最高的状态：
    completed > processing > pending > rejected
    """
    priority = {'completed': 4, 'processing': 3, 'pending': 2, 'rejected': 1}
    with Session() as session:
        try:
            rows = session.query(
                MiniAppRequest.tmdb_id, MiniAppRequest.status
            ).filter(MiniAppRequest.tg == tg).all()
            result = {}
            for tmdb_id, status in rows:
                if tmdb_id and (
                    tmdb_id not in result or
                    priority.get(status, 0) > priority.get(result[tmdb_id], 0)
                ):
                    result[tmdb_id] = status
            return result
        except Exception as e:
            LOGGER.error(f"【MiniApp】查询申请状态字典失败: {e}")
            return {}


def sql_get_pending_requests() -> List[MiniAppRequest]:
    """获取所有待处理且未通知的求片申请（供 webhook 触发检查使用）"""
    with Session() as session:
        try:
            rows = session.query(MiniAppRequest).filter(
                MiniAppRequest.status.in_(['pending', 'processing']),
                MiniAppRequest.notified == 0
            ).all()
            return rows
        except Exception as e:
            LOGGER.error(f"【MiniApp】查询待处理申请失败: {e}")
            return []


def sql_mark_request_completed(request_id: int) -> bool:
    """将申请标记为已完成并已通知"""
    with Session() as session:
        try:
            req = session.query(MiniAppRequest).filter(
                MiniAppRequest.id == request_id
            ).first()
            if req:
                req.status = 'completed'
                req.notified = 1
                req.updated_at = datetime.now()
                session.commit()
                return True
            return False
        except Exception as e:
            LOGGER.error(f"【MiniApp】标记申请完成失败: {e}")
            session.rollback()
            return False


def sql_get_requests_stats() -> dict:
    """返回求片申请各状态数量统计（供管理后台展示）"""
    with Session() as session:
        try:
            total = session.query(MiniAppRequest).count()
            pending = session.query(MiniAppRequest).filter(MiniAppRequest.status == 'pending').count()
            processing = session.query(MiniAppRequest).filter(MiniAppRequest.status == 'processing').count()
            completed = session.query(MiniAppRequest).filter(MiniAppRequest.status == 'completed').count()
            rejected = session.query(MiniAppRequest).filter(MiniAppRequest.status == 'rejected').count()
            return {
                "total": total, "pending": pending,
                "processing": processing, "completed": completed, "rejected": rejected,
            }
        except Exception as e:
            LOGGER.error(f"【MiniApp】统计申请状态失败: {e}")
            return {"total": 0, "pending": 0, "processing": 0, "completed": 0, "rejected": 0}


def sql_get_all_requests(status: Optional[str] = None, page: int = 1, page_size: int = 20,
                         keyword: str = "") -> dict:
    """管理员查询所有求片申请（支持状态过滤和分页）"""
    from bot.sql_helper.sql_emby import Emby
    with Session() as session:
        try:
            q = session.query(MiniAppRequest, Emby.name).outerjoin(
                Emby, Emby.tg == MiniAppRequest.tg
            )
            if status:
                q = q.filter(MiniAppRequest.status == status)
            if keyword:
                q = q.filter(MiniAppRequest.title.contains(keyword))
            total = q.count()
            rows = q.order_by(MiniAppRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
            items = []
            for req, emby_name in rows:
                d = _request_to_dict(req)
                d["emby_name"] = emby_name or str(req.tg)
                items.append(d)
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": items,
            }
        except Exception as e:
            LOGGER.error(f"【MiniApp】管理员查询申请失败: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "items": []}


def sql_get_request_by_id(request_id: int) -> Optional[MiniAppRequest]:
    """按 ID 查询单条申请（返回 ORM 对象供通知使用）"""
    with Session() as session:
        try:
            return session.query(MiniAppRequest).filter(MiniAppRequest.id == request_id).first()
        except Exception as e:
            LOGGER.error(f"【MiniApp】查询申请 {request_id} 失败: {e}")
            return None


def sql_update_request_status(request_id: int, status: str,
                               note: Optional[str] = None) -> Optional[MiniAppRequest]:
    """更新申请状态（管理员审批/拒绝），返回更新后的 ORM 对象"""
    with Session() as session:
        try:
            req = session.query(MiniAppRequest).filter(MiniAppRequest.id == request_id).first()
            if not req:
                return None
            req.status = status
            req.updated_at = datetime.now()
            if note is not None:
                req.note = note
            if status in ('completed', 'rejected'):
                req.notified = 1
            session.commit()
            session.refresh(req)
            return req
        except Exception as e:
            LOGGER.error(f"【MiniApp】更新申请状态失败: {e}")
            session.rollback()
            return None


def sql_update_request(request_id: int, status: Optional[str] = None,
                        note: Optional[str] = None) -> Optional[MiniAppRequest]:
    """管理员编辑申请（可修改状态和管理员备注）"""
    with Session() as session:
        try:
            req = session.query(MiniAppRequest).filter(MiniAppRequest.id == request_id).first()
            if not req:
                return None
            if status is not None:
                req.status = status
            if note is not None:
                req.note = note
            req.updated_at = datetime.now()
            session.commit()
            session.refresh(req)
            return req
        except Exception as e:
            LOGGER.error(f"【MiniApp】编辑申请失败: {e}")
            session.rollback()
            return None


def sql_delete_request(request_id: int) -> bool:
    """管理员删除求片申请"""
    with Session() as session:
        try:
            req = session.query(MiniAppRequest).filter(MiniAppRequest.id == request_id).first()
            if not req:
                return False
            session.delete(req)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【MiniApp】删除申请失败: {e}")
            session.rollback()
            return False


def sql_count_requests_in_period(tg: int, days: int) -> int:
    """统计用户在指定天数内提交的求片数量（pending/processing/completed 均计入）"""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)
    with Session() as session:
        try:
            return session.query(MiniAppRequest).filter(
                MiniAppRequest.tg == tg,
                MiniAppRequest.created_at >= cutoff,
                MiniAppRequest.status.in_(['pending', 'processing', 'completed']),
            ).count()
        except Exception as e:
            LOGGER.error(f"【MiniApp】统计求片数量失败: {e}")
            return 0


# ── 序列化辅助 ─────────────────────────────────────────────────────────────────

def _request_to_dict(r: MiniAppRequest) -> dict:
    return {
        "id": r.id,
        "tg": r.tg,
        "tmdb_id": r.tmdb_id,
        "media_type": r.media_type,
        "title": r.title,
        "orig_title": r.orig_title,
        "poster": r.poster,
        "year": r.year,
        "status": r.status,
        "note": r.note,          # 管理员备注
        "user_note": r.user_note if hasattr(r, 'user_note') else None,  # 用户备注
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
    }
