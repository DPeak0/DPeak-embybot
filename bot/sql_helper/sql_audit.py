"""
审计日志 ORM + CRUD
table: audit_log

category 值域:
  credits   — 积分变动
  code      — 注册码/邀请码操作
  account   — 账号变动（注册/封禁/解封/等级/到期）
  settings  — 系统设置变更
  login     — 管理员登录/登出
  request   — 求片审批操作
  bot_cmd   — Bot 管理员指令
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Column, DateTime, Index, String, Text, text
)

from bot.sql_helper import Base, Session, engine


class AuditLog(Base):
    __tablename__ = "audit_log"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    category      = Column(String(20),  nullable=False)   # credits/code/account/settings/login/request/bot_cmd
    action        = Column(String(50),  nullable=False)   # 具体操作，如 ban/unban/register/checkin...
    source        = Column(String(20),  nullable=True)    # web / bot / scheduler
    operator_tg   = Column(BigInteger,  nullable=True)    # 操作者 TG ID
    operator_name = Column(String(100), nullable=True)    # 操作者昵称/用户名
    target_tg     = Column(BigInteger,  nullable=True)    # 被操作对象 TG ID
    target_name   = Column(String(100), nullable=True)    # 被操作对象昵称
    before_val    = Column(String(500), nullable=True)    # 变更前值
    after_val     = Column(String(500), nullable=True)    # 变更后值
    detail        = Column(Text,        nullable=True)    # 详情描述（自由文本）
    note          = Column(Text,        nullable=True)    # 备注
    ip            = Column(String(50),  nullable=True)    # 操作来源 IP（Web 层填写）
    created_at    = Column(DateTime,    nullable=False, default=datetime.now)

    __table_args__ = (
        Index("ix_audit_log_category",   "category"),
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_target_tg",  "target_tg"),
    )


def _migrate_audit_log():
    """确保 audit_log 表存在（首次运行自动建表）"""
    try:
        Base.metadata.create_all(engine, tables=[AuditLog.__table__], checkfirst=True)
    except Exception as e:
        from bot import LOGGER
        LOGGER.warning(f"【AuditLog】建表失败: {e}")


_migrate_audit_log()


# ── 写入 ─────────────────────────────────────────────────────────────────────

def log_audit(
    *,
    category: str,
    action: str,
    source: str = "bot",
    operator_tg: int = None,
    operator_name: str = None,
    target_tg: int = None,
    target_name: str = None,
    before_val: str = None,
    after_val: str = None,
    detail: str = None,
    note: str = None,
    ip: str = None,
) -> None:
    """同步写入一条审计日志（失败时仅记录 warning，不阻断业务）"""
    try:
        row = AuditLog(
            category=category,
            action=action,
            source=source,
            operator_tg=operator_tg,
            operator_name=operator_name,
            target_tg=target_tg,
            target_name=target_name,
            before_val=str(before_val)[:499] if before_val is not None else None,
            after_val=str(after_val)[:499] if after_val is not None else None,
            detail=detail,
            note=note,
            ip=ip,
            created_at=datetime.now(),
        )
        with Session() as session:
            session.add(row)
            session.commit()
    except Exception as e:
        try:
            from bot import LOGGER
            LOGGER.warning(f"【AuditLog】写入失败 category={category} action={action}: {e}")
        except Exception:
            pass


# ── 查询 ─────────────────────────────────────────────────────────────────────

def query_audit_logs(
    *,
    category: str = None,
    action: str = None,
    source: str = None,
    keyword: str = None,      # 模糊匹配 operator_name / target_name / detail
    operator_tg: int = None,  # 按操作者 TG ID 筛选
    target_tg: int = None,    # 按操作目标 TG ID 筛选
    date_from: datetime = None,
    date_to: datetime = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """分页查询审计日志，返回 {total, page, page_size, items}"""
    from sqlalchemy import or_
    with Session() as session:
        q = session.query(AuditLog)
        if category:
            q = q.filter(AuditLog.category == category)
        if action:
            q = q.filter(AuditLog.action == action)
        if source:
            q = q.filter(AuditLog.source == source)
        if operator_tg:
            q = q.filter(AuditLog.operator_tg == operator_tg)
        if target_tg:
            q = q.filter(AuditLog.target_tg == target_tg)
        if keyword:
            kw = f"%{keyword}%"
            q = q.filter(or_(
                AuditLog.operator_name.ilike(kw),
                AuditLog.target_name.ilike(kw),
                AuditLog.detail.ilike(kw),
                AuditLog.action.ilike(kw),
            ))
        if date_from:
            q = q.filter(AuditLog.created_at >= date_from)
        if date_to:
            q = q.filter(AuditLog.created_at <= date_to)

        total = q.count()
        rows  = q.order_by(AuditLog.created_at.desc()) \
                 .offset((page - 1) * page_size) \
                 .limit(page_size).all()

        return {
            "total":     total,
            "page":      page,
            "page_size": page_size,
            "items":     [_row_to_dict(r) for r in rows],
        }


def delete_audit_logs_before(dt: datetime) -> int:
    """删除 created_at < dt 的日志，返回删除行数"""
    with Session() as session:
        n = session.query(AuditLog).filter(AuditLog.created_at < dt).delete()
        session.commit()
        return n


def get_audit_operator_names(tg_ids: list) -> dict:
    """
    给定一组 TG ID，从 audit_log 中查出每个 ID 最近一次的 operator_name。
    返回 {tg_id: name_str} 字典，无记录时 name 为空字符串。
    """
    if not tg_ids:
        return {}
    result = {}
    with Session() as session:
        for tg_id in tg_ids:
            row = (
                session.query(AuditLog.operator_name)
                .filter(AuditLog.operator_tg == tg_id, AuditLog.operator_name.isnot(None))
                .order_by(AuditLog.created_at.desc())
                .first()
            )
            result[tg_id] = row[0] if row else ""
    return result


def _row_to_dict(r: AuditLog) -> dict:
    return {
        "id":            r.id,
        "category":      r.category,
        "action":        r.action,
        "source":        r.source or "",
        "operator_tg":   r.operator_tg,
        "operator_name": r.operator_name or "",
        "target_tg":     r.target_tg,
        "target_name":   r.target_name or "",
        "before_val":    r.before_val or "",
        "after_val":     r.after_val or "",
        "detail":        r.detail or "",
        "note":          r.note or "",
        "ip":            r.ip or "",
        "created_at":    r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
    }
